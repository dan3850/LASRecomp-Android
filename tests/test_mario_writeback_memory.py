"""Native-vs-reference checks for scalar and pair writeback memory modes.

Tests guest RAM content, SP/base register updates, and no writeback after faults.
Uses synthetic instructions only: no game code or binaries in repository.
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
BASE = 0x30000000
MASK64 = (1 << 64) - 1


def pair(load, width, mode, rt=1, rt2=2, rn=0, imm=0):
    bases = {4: 0x29000000, 8: 0xA9000000}
    mode_bits = {"offset": 0, "post": 0xFF800000, "pre": 0x00800000}
    # Post-index changes 0x29000000 to 0x28800000; for W/X alike.
    mode_bits["post"] = -0x00800000
    return ((bases[width] + mode_bits[mode]) | (int(load) << 22) |
            ((imm & 127) << 15) | (rt2 << 10) | (rn << 5) | rt)


def scalar(load, width, mode, rt=1, rn=0, imm=0):
    sizes = {1: 0, 2: 1, 4: 2, 8: 3}
    modes = {"unscaled": 0, "post": 1, "pre": 3}
    return (0x38000000 | (sizes[width] << 30) | (int(load) << 22) |
            ((imm & 511) << 12) | (modes[mode] << 10) | (rn << 5) | rt)


class TestWritebackMemory(unittest.TestCase):
    def test_reject_constrained_unpredictable_overlaps(self):
        for mode in ("pre", "post"):
            for load in (False, True):
                self.assertIsNone(translate([pair(load, 8, mode, rt=0, rn=0), RET]))
                self.assertIsNone(translate([pair(load, 8, mode, rt2=0, rn=0), RET]))
                self.assertIsNone(translate([scalar(load, 8, mode, rt=0, rn=0), RET]))
        # Offset pair without writeback still permits overlapping destination.
        self.assertIsNotNone(translate([pair(True, 8, "offset", rt=0, rn=0), RET]))

    @unittest.skipUnless(shutil.which("clang"), "clang required")
    def test_all_modes_against_reference(self):
        cases = []
        for width in (4, 8):
            for load in (False, True):
                for mode in ("offset", "pre", "post"):
                    for immediate in (-2, 0, 2):
                        for rn in (0, 31):
                            cases.append(("pair", pair(load, width, mode, rn=rn, imm=immediate)))
        for width in (1, 2, 4, 8):
            for load in (False, True):
                for mode in ("unscaled", "pre", "post"):
                    for immediate in (-7, 0, 7):
                        for rn in (0, 31):
                            cases.append(("scalar", scalar(load, width, mode, rn=rn, imm=immediate)))
        with tempfile.TemporaryDirectory(prefix="mario-writeback-") as tmp:
            source = Path(tmp) / "writeback.c"
            binary = Path(tmp) / "writeback.so"
            parts = [HEADER]
            for index, (_, word) in enumerate(cases):
                body = translate([word, RET])
                self.assertIsNotNone(body, (index, hex(word)))
                parts += [f"void run_{index}(MarioA64State *s) {{", *body, "}"]
            source.write_text("\n".join(parts) + "\n", encoding="utf-8")
            subprocess.run(
                ["clang", "-std=c11", "-O2", "-fPIC", "-shared", "-Wall",
                 "-Wextra", "-Werror", str(source), "-o", str(binary)],
                check=True, capture_output=True)
            library = ctypes.CDLL(str(binary))
            for index, (category, word) in enumerate(cases):
                fn = getattr(library, f"run_{index}")
                fn.argtypes = [ctypes.POINTER(State)]
                fn.restype = None
                for base_offset in (0, 24, 48, 60):
                    raw = bytes(range(64))
                    mem = (ctypes.c_uint8 * len(raw)).from_buffer_copy(raw)
                    state = State()
                    state.x[0] = BASE + base_offset
                    state.x[1] = 0x1234567887654321
                    state.x[2] = 0xABCDEF0099887766
                    state.x[30] = 0x20000000
                    state.sp = BASE + base_offset
                    state.pc = 0x10000000
                    state.nzcv = 0xA0000000
                    state.mem = ctypes.cast(mem, ctypes.POINTER(ctypes.c_uint8))
                    state.mem_base = BASE
                    state.mem_size = len(raw)
                    expected_memory = bytearray(raw)
                    try:
                        reference = run_reference(
                            struct.pack("<2I", word, RET),
                            state, expected_memory, BASE)
                        expected_fault = False
                    except MemoryError:
                        expected_fault = True
                    fn(ctypes.byref(state))
                    label = (index, category, hex(word), base_offset)
                    self.assertEqual(bool(state.fault), expected_fault, label)
                    self.assertEqual(bytes(mem), bytes(expected_memory), label)
                    if expected_fault:
                        self.assertEqual(state.pc, 0x10000000, label)
                        self.assertEqual(state.sp, BASE + base_offset, label)
                        self.assertEqual(state.x[0], BASE + base_offset, label)
                    else:
                        self.assertEqual(snapshot(state), reference, label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
