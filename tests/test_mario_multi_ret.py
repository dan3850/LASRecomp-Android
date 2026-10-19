"""Opt-in multi-RET ARM64 leaf tests; legacy single-RET remains unchanged.

No ROM/NSO data; native C must match the independent reference interpreter.
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
ADD_X1_1 = 0x91000421
CBZ_X0_PLUS2 = 0xB4000040
B_PLUS2 = 0x14000002
BEQ_PLUS2 = 0x54000040


class TestMultiRet(unittest.TestCase):
    def test_explicit_opt_in_preserves_legacy_rejections(self):
        self.assertIsNone(translate([RET, RET]))
        self.assertIsNotNone(translate([RET, RET], allow_multiple_ret=True))
        self.assertIsNone(translate([RET, ADD_X1_1]))
        self.assertIsNone(translate([RET, ADD_X1_1], allow_multiple_ret=True))
        self.assertIsNone(translate([RET, 0xD4200000, RET], allow_multiple_ret=True))
        self.assertIsNone(translate([B_PLUS2, RET], allow_multiple_ret=True))
        state = State()
        state.x[30] = 0x1234
        code = struct.pack("<2I", RET, RET)
        with self.assertRaises(ValueError):
            run_reference(code, state)
        self.assertEqual(run_reference(code, state, allow_multiple_ret=True)[2], 0x1234)

    @unittest.skipUnless(shutil.which("clang"), "clang required for generated C")
    def test_multiple_returns_with_forward_branch(self):
        cases = [
            [RET, RET],
            [CBZ_X0_PLUS2, RET, ADD_X1_1, RET],
            [B_PLUS2, RET, ADD_X1_1, RET],
            [BEQ_PLUS2, RET, ADD_X1_1, RET],
            [ADD_X1_1, RET, ADD_X1_1, RET],
        ]
        with tempfile.TemporaryDirectory(prefix="mario-multi-ret-") as tmp:
            source, binary = Path(tmp) / "multi.c", Path(tmp) / "multi.so"
            functions = [HEADER]
            for i, words in enumerate(cases):
                body = translate(words, allow_multiple_ret=True)
                self.assertIsNotNone(body, (i, words))
                functions += [f"void case_{i}(MarioA64State *s) {{", *body, "}"]
            source.write_text("\n".join(functions) + "\n", encoding="utf-8")
            subprocess.run(
                ["clang", "-std=c11", "-O2", "-fPIC", "-shared",
                 "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                check=True, capture_output=True)
            lib = ctypes.CDLL(str(binary))
            for i, words in enumerate(cases):
                fn = getattr(lib, f"case_{i}")
                fn.argtypes = [ctypes.POINTER(State)]
                guest = struct.pack("<" + "I" * len(words), *words)
                for x0 in (0, 1, 0xFFFFFFFFFFFFFFFF):
                    for flags in (0, 0x40000000, 0xF0000000):
                        state = State()
                        state.x[0], state.x[1] = x0, 100
                        state.x[30] = 0x20000000
                        state.pc = 0x10000000
                        state.nzcv = flags
                        expected = run_reference(
                            guest, state, allow_multiple_ret=True)
                        fn(ctypes.byref(state))
                        self.assertEqual(snapshot(state), expected,
                                         (i, x0, flags))

if __name__ == "__main__":
    unittest.main(verbosity=2)
