"""Regression: all ARM64 B.cond variants must compile and match reference.

Previously GT/LE emitted undeclared n/v C locals when parsing predicates.
Tests all 14 supported conditions and every 4-bit NZCV combination.
"""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_leaf_codegen import HEADER, translate
from mario_a64_reference import run_reference
from mario_leaf_verify import State, snapshot

RET = 0xD65F03C0
ADD_X0_1 = 0x91000400


class TestAllConditionalBranches(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang"), "clang required for generated C")
    def test_all_conditions_all_nzcv(self):
        with tempfile.TemporaryDirectory(prefix="mario-bcond-all-") as root:
            source = Path(root) / "bcond.c"
            binary = Path(root) / "bcond.so"
            code = [HEADER]
            for cond in range(14):
                # B.cond to RET skips the ADD when the condition is true.
                words = [0x54000000 | (2 << 5) | cond, ADD_X0_1, RET]
                body = translate(words)
                self.assertIsNotNone(body, cond)
                code += [f"void case_{cond}(MarioA64State *s) {{", *body, "}"]
            source.write_text("\n".join(code) + "\n", encoding="utf-8")
            subprocess.run(
                ["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                 "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                check=True, capture_output=True)
            dll = ctypes.CDLL(str(binary))
            for cond in range(14):
                fn = getattr(dll, f"case_{cond}")
                fn.argtypes = [ctypes.POINTER(State)]
                words = [0x54000000 | (2 << 5) | cond, ADD_X0_1, RET]
                guest_code = struct.pack("<3I", *words)
                for nzcv in range(16):
                    state = State()
                    state.pc = 0x10000000
                    state.x[0] = 7
                    state.x[30] = 0x20000000
                    state.nzcv = nzcv << 28
                    expected = run_reference(guest_code, state)
                    fn(ctypes.byref(state))
                    self.assertEqual(snapshot(state), expected,
                                     f"cond={cond}, NZCV={nzcv:04b}")

    def test_reject_reserved_conditions(self):
        for cond in (14, 15):
            words = [0x54000000 | (2 << 5) | cond, ADD_X0_1, RET]
            self.assertIsNone(translate(words))


if __name__ == "__main__":
    unittest.main(verbosity=2)
