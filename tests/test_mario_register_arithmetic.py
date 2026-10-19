"""Native differential checks for ARM64 ADD/SUB shifted-register LSL."""
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

def op(sf, subtract, flags, shift, rd=2, rn=0, rm=1):
    return (0x0B000000 | (sf << 31) | (subtract << 30) |
            (flags << 29) | (rm << 16) | (shift << 10) | (rn << 5) | rd)

class TestRegisterArithmetic(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang"), "clang required")
    def test_native_reference(self):
        with tempfile.TemporaryDirectory(prefix="mario-regarith-") as tmp:
            source = Path(tmp) / "test.c"
            for sf in (0, 1):
                for subtract in (0, 1):
                    for flags in (0, 1):
                        for shift in (0, 1, 7, 31 if not sf else 63):
                            library = Path(tmp) / f"test_{sf}_{subtract}_{flags}_{shift}.so"
                            words = [op(sf, subtract, flags, shift), RET]
                            body = translate(words)
                            self.assertIsNotNone(body)
                            source.write_text("\n".join([HEADER, "void test(MarioA64State *s) {", *body, "}"]))
                            subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                                           check=True, capture_output=True)
                            fn = ctypes.CDLL(str(library)).test
                            fn.argtypes = [ctypes.POINTER(State)]
                            for a, b in ((0, 0), (1, 1), (0xFFFFFFFFFFFFFFFF, 1),
                                         (0x8000000000000000, 0x8000000000000000),
                                         (0x7FFFFFFFFFFFFFFF, 1)):
                                state = State()
                                state.x[0], state.x[1] = a, b
                                state.x[30] = 0x1234
                                state.nzcv = 0xF0000000
                                expected = run_reference(struct.pack("<2I", *words), state)
                                fn(ctypes.byref(state))
                                self.assertEqual(snapshot(state), expected)

    def test_reject_reserved_shift(self):
        self.assertIsNone(translate([op(0, 0, 0, 32), RET]))
        self.assertIsNone(translate([op(1, 0, 0, 0) | (1 << 22), RET]))

if __name__ == "__main__":
    unittest.main(verbosity=2)
