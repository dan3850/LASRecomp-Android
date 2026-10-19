"""Native differential tests for PC-relative ADR/ADRP and CSEL/CSINC."""
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
NOP = 0xD503201F


def adr(delta, page=False, rd=0):
    if page:
        assert -(1 << 20) <= delta < (1 << 20)
    else:
        assert -(1 << 20) <= delta < (1 << 20)
    encoded = delta & ((1 << 21) - 1)
    return ((0x90000000 if page else 0x10000000) |
            ((encoded & 3) << 29) | ((encoded >> 2) << 5) | rd)


def select(sf, increment, cond, rn=0, rm=1, rd=2):
    return (0x1A800000 | (sf << 31) | (int(increment) << 10) |
            (rm << 16) | (cond << 12) | (rn << 5) | rd)


@unittest.skipUnless(shutil.which("clang"), "Clang required")
class TestAddressConditional(unittest.TestCase):
    def test_native_vs_reference(self):
        scenarios = []
        for page in (False, True):
            for delta in (0, 1, -1, 4095, -4096, (1 << 20) - 1, -(1 << 20)):
                for prefix in ([], [NOP]):
                    scenarios.append(prefix + [adr(delta, page), RET])
        for sf in (0, 1):
            for increment in (False, True):
                for cond in range(14):
                    scenarios.append([select(sf, increment, cond), RET])
        # CSET W0, EQ = CSINC W0,WZR,WZR,NE.
        scenarios.append([select(0, True, 1, rn=31, rm=31, rd=0), RET])
        # Register 31 discards ADR/ADRP results, and conditional selects.
        scenarios += [[adr(-1, False, 31), RET],
                      [adr(4, True, 31), RET],
                      [select(1, True, 1, 31, 31, 31), RET]]
        with tempfile.TemporaryDirectory(prefix="mario-adr-cond-") as tmp:
            source, library = Path(tmp) / "test.c", Path(tmp) / "test.so"
            generated = [HEADER]
            for i, words in enumerate(scenarios):
                body = translate(words)
                self.assertIsNotNone(body, (i, words))
                generated += [f"void case_{i}(MarioA64State *s) {{", *body, "}"]
            source.write_text("\n".join(generated) + "\n", encoding="utf-8")
            subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                           check=True, capture_output=True)
            dll = ctypes.CDLL(str(library))
            for i, words in enumerate(scenarios):
                fn = getattr(dll, f"case_{i}")
                fn.argtypes = [ctypes.POINTER(State)]
                for pc in (0x10000000, 0x10000FFC, 0x10001001):
                    for flags in (0, 0xF0000000, 0x40000000, 0x20000000,
                                  0x80000000, 0x10000000):
                        state = State()
                        state.pc = pc
                        state.x[0] = 0x123456789ABCDEF0
                        state.x[1] = 0xFFFFFFFFFFFFFFFF
                        state.x[2] = 0x5555555555555555
                        state.x[30] = 0x20000000
                        state.nzcv = flags
                        reference = run_reference(struct.pack("<" + "I" * len(words), *words), state)
                        fn(ctypes.byref(state))
                        self.assertEqual(snapshot(state), reference,
                                         (i, pc, flags, [hex(w) for w in words]))

    def test_reject_unhandled_cond(self):
        for cond in (14, 15):
            self.assertIsNone(translate([select(1, False, cond), RET]))
            self.assertIsNone(translate([select(0, True, cond), RET]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
