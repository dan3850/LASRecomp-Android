"""Native differential tests for forward TBZ/TBNZ, W/X bit selection."""
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

def tb(bit, nonzero, reg=0, displacement=2):
    return (0x36000000 | ((bit >> 5) << 31) |
            (int(nonzero) << 24) | ((bit & 31) << 19) |
            (displacement << 5) | reg)

class TestTBZ(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang"), "Clang required")
    def test_native_and_reference(self):
        with tempfile.TemporaryDirectory(prefix="mario-tbz-") as tmp:
            for bit in (0, 7, 31, 32, 63):
                for nonzero in (False, True):
                    words = [tb(bit, nonzero), 0x91000421, 0x91000821, RET]
                    body = translate(words)
                    self.assertIsNotNone(body, (bit, nonzero))
                    source = Path(tmp) / "test.c"
                    library = Path(tmp) / "test.so"
                    source.write_text("\n".join([HEADER, "void test(MarioA64State *s) {", *body, "}"]))
                    subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                                    "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                                   check=True, capture_output=True)
                    fn = ctypes.CDLL(str(library)).test
                    fn.argtypes = [ctypes.POINTER(State)]
                    for value in (0, 1 << bit, (1 << 64) - 1):
                        state = State()
                        state.x[0] = value
                        state.x[1] = 5
                        state.x[30] = 0x1234
                        state.nzcv = 0xA0000000
                        expected = run_reference(struct.pack("<4I", *words), state)
                        fn(ctypes.byref(state))
                        self.assertEqual(snapshot(state), expected)

    def test_reject_backward_external(self):
        for word in (tb(0, False, displacement=0),
                     tb(0, True, displacement=0x3fff),
                     tb(0, False, displacement=4)):
            self.assertIsNone(translate([word, RET]))

if __name__ == "__main__":
    unittest.main(verbosity=2)
