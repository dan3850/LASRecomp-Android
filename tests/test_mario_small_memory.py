"""Native differential tests for unsigned-offset byte and halfword RAM access."""
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
BASE = 0x30000000


def ls(load, width, rt=1, rn=0, imm=0):
    encodings = {
        (False, 1): 0x39000000, (True, 1): 0x39400000,
        (False, 2): 0x79000000, (True, 2): 0x79400000,
    }
    assert 0 <= imm < 4096
    return encodings[(load, width)] | (imm << 10) | (rn << 5) | rt


@unittest.skipUnless(shutil.which("clang"), "Clang required")
class TestByteHalfword(unittest.TestCase):
    def test_native_reference_and_memory(self):
        cases = []
        for width in (1, 2):
            for load in (False, True):
                for rt in (1, 31):
                    for rn in (0, 31):
                        for offset in (0, 1, 17):
                            cases.append([ls(load, width, rt, rn, offset), RET])
        with tempfile.TemporaryDirectory(prefix="mario-smallmem-") as tmp:
            source, libfile = Path(tmp) / "test.c", Path(tmp) / "test.so"
            lines = [HEADER]
            for i, words in enumerate(cases):
                body = translate(words)
                self.assertIsNotNone(body, words)
                lines += [f"void case_{i}(MarioA64State *s) {{", *body, "}"]
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(libfile)],
                           capture_output=True, check=True)
            dll = ctypes.CDLL(str(libfile))
            for i, words in enumerate(cases):
                fn = getattr(dll, f"case_{i}")
                fn.argtypes = [ctypes.POINTER(State)]
                for base_offset in (0, 17, 63):
                    original = bytes(range(64))
                    ram = (ctypes.c_uint8 * len(original)).from_buffer_copy(original)
                    state = State()
                    state.x[0] = BASE + base_offset
                    state.x[1] = 0xABCDEF123456FF80
                    state.x[30] = 0x20000000
                    state.sp = BASE + base_offset
                    state.pc = 0x10000000
                    state.nzcv = 0xB0000000
                    state.mem = ctypes.cast(ram, ctypes.POINTER(ctypes.c_uint8))
                    state.mem_base = BASE
                    state.mem_size = len(original)
                    expected_ram = bytearray(original)
                    try:
                        expected = run_reference(
                            struct.pack("<2I", *words), state, expected_ram, BASE)
                        expected_fault = False
                    except MemoryError:
                        expected_fault = True
                    fn(ctypes.byref(state))
                    self.assertEqual(bool(state.fault), expected_fault,
                                     (i, base_offset, "fault"))
                    self.assertEqual(bytes(ram), expected_ram,
                                     (i, base_offset, "memory"))
                    if expected_fault:
                        self.assertEqual(state.pc, 0x10000000)
                    else:
                        self.assertEqual(snapshot(state), expected,
                                         (i, base_offset, "registers"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
