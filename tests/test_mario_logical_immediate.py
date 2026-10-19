"""Differential native tests for ARM64 logical immediate operations."""
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

def logical(sf, opc, n, immr, imms, rn=0, rd=1):
    return (0x12000000 | (sf << 31) | (opc << 29) | (n << 22) |
            (immr << 16) | (imms << 10) | (rn << 5) | rd)

class TestLogicalImmediate(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang"), "clang required")
    def test_native_reference(self):
        with tempfile.TemporaryDirectory(prefix="mario-logimm-") as tmp:
            source, library = Path(tmp) / "test.c", Path(tmp) / "test.so"
            for sf, n, imms, immr in ((0, 0, 7, 0), (0, 0, 15, 9),
                                       (1, 1, 15, 3), (1, 1, 0, 63),
                                       (1, 0, 39, 12)):
                for opc in range(4):
                    words = [logical(sf, opc, n, immr, imms), RET]
                    body = translate(words)
                    self.assertIsNotNone(body, (sf, opc, n, imms, immr))
                    source.write_text("\n".join([HEADER, "void test(MarioA64State *s) {", *body, "}"]))
                    subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                                    "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                                   check=True, capture_output=True)
                    fn = ctypes.CDLL(str(library)).test
                    fn.argtypes = [ctypes.POINTER(State)]
                    for value in (0, 1, 0xFFFFFFFF, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF):
                        state = State()
                        state.x[0] = value
                        state.x[1] = 0xF0F0F0F0F0F0F0F0
                        state.x[30] = 0x1234
                        state.nzcv = 0xF0000000
                        expected = run_reference(struct.pack("<2I", *words), state)
                        fn(ctypes.byref(state))
                        self.assertEqual(snapshot(state), expected)

    def test_reserved(self):
        for word in (logical(0, 0, 1, 0, 0), logical(1, 3, 1, 0, 63)):
            self.assertIsNone(translate([word, RET]))

if __name__ == "__main__":
    unittest.main(verbosity=2)
