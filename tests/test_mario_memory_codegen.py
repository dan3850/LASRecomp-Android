#!/usr/bin/env python3
"""Native C vs independent ARM64 memory semantics; no game files required."""
import ctypes
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_leaf_codegen import HEADER, translate
from mario_a64_reference import run_reference

BASE = 0x30000000
RET = 0xD65F03C0


def ls(load, width, rt, rn, imm=0):
    base = {(True, 4): 0xB9400000, (False, 4): 0xB9000000,
            (True, 8): 0xF9400000, (False, 8): 0xF9000000}[(load, width)]
    return base | (imm << 10) | (rn << 5) | rt


class State(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint64 * 31), ("sp", ctypes.c_uint64),
        ("pc", ctypes.c_uint64), ("nzcv", ctypes.c_uint64),
        ("mem", ctypes.POINTER(ctypes.c_uint8)),
        ("mem_base", ctypes.c_uint64), ("mem_size", ctypes.c_uint64),
        ("fault", ctypes.c_uint64),
    ]


def compare(words, overrides=None, size=64):
    body = translate(words)
    if body is None:
        raise AssertionError("translator rejected supported test case")
    with tempfile.TemporaryDirectory(prefix="mario-memory-") as tmp:
        source = Path(tmp) / "test.c"
        libpath = Path(tmp) / "test.so"
        source.write_text(
            HEADER + "\nvoid test(MarioA64State *s) {\n" + "\n".join(body) + "\n}\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-shared", "-fPIC", str(source), "-o", str(libpath)],
            check=True,
        )
        dll = ctypes.CDLL(str(libpath))
        ram = (ctypes.c_uint8 * size)(*range(size))
        s = State()
        for i in range(31):
            s.x[i] = i * 0x1111
        s.x[30] = 0x20000000
        s.sp = BASE + 16
        s.pc = 0x10000000
        s.nzcv = 0xA0000000
        s.mem = ctypes.cast(ram, ctypes.POINTER(ctypes.c_uint8))
        s.mem_base = BASE
        s.mem_size = size
        for reg, value in (overrides or {}).items():
            s.x[reg] = value
        reference_memory = bytearray(ram)
        packed = struct.pack("<" + "I" * len(words), *words)
        try:
            expected = run_reference(packed, s, reference_memory, BASE)
            reference_fault = False
        except MemoryError:
            reference_fault = True
        func = dll.test
        func.argtypes = [ctypes.POINTER(State)]
        func.restype = None
        func(ctypes.byref(s))
        assert bool(s.fault) == reference_fault, "mismatched access fault"
        assert bytes(ram) == bytes(reference_memory), "mismatched guest memory"
        if reference_fault:
            assert s.pc == 0x10000000, "PC advanced on fault"
        else:
            assert (tuple(s.x), s.sp, s.pc, s.nzcv & 0xF0000000) == expected, "mismatched CPU state"
        return s, bytes(ram)


class TestMemory(unittest.TestCase):
    def test_load_w_zero_extend(self):
        s, _ = compare([ls(True, 4, 2, 0, 1), RET], {0: BASE + 8})
        self.assertEqual(s.x[2], int.from_bytes(bytes(range(12, 16)), "little"))

    def test_load_x(self):
        s, _ = compare([ls(True, 8, 2, 0, 1), RET], {0: BASE + 8})
        self.assertEqual(s.x[2], int.from_bytes(bytes(range(16, 24)), "little"))

    def test_store_w_then_load_w(self):
        s, ram = compare([ls(False, 4, 1, 0, 1), ls(True, 4, 2, 0, 1), RET],
                         {0: BASE + 8, 1: 0xABCDEF0012345678})
        self.assertEqual(s.x[2], 0x12345678)
        self.assertEqual(ram[12:16], b"\x78\x56\x34\x12")

    def test_store_x_then_load_x(self):
        s, ram = compare([ls(False, 8, 1, 0), ls(True, 8, 2, 0), RET],
                         {0: BASE + 8, 1: 0x0123456789ABCDEF})
        self.assertEqual(s.x[2], 0x0123456789ABCDEF)
        self.assertEqual(ram[8:16], b"\xef\xcd\xab\x89\x67\x45\x23\x01")

    def test_sp_base(self):
        s, _ = compare([ls(True, 4, 0, 31), RET])
        self.assertEqual(s.x[0], int.from_bytes(bytes(range(16, 20)), "little"))

    def test_zero_register_store_and_discard_load(self):
        s, ram = compare([ls(False, 8, 31, 0), ls(True, 8, 31, 0), RET],
                         {0: BASE + 8})
        self.assertEqual(ram[8:16], bytes(8))
        self.assertEqual(s.x[0], BASE + 8)

    def test_oob_store_rejected_without_host_write(self):
        s, ram = compare([ls(False, 8, 1, 0), RET], {0: BASE + 60})
        self.assertEqual(s.fault, 1)
        self.assertEqual(ram, bytes(range(64)))

    def test_pair_load_and_store(self):
        # LDP X2, X3, [X0] and STP X2, X3, [X0, #16].
        ldp = 0xA9400000 | (3 << 10) | 2
        stp = 0xA9000000 | (2 << 15) | (3 << 10) | 2
        s, ram = compare([ldp, stp, RET], {0: BASE + 8})
        self.assertEqual(s.x[2], int.from_bytes(bytes(range(8, 16)), "little"))
        self.assertEqual(s.x[3], int.from_bytes(bytes(range(16, 24)), "little"))
        self.assertEqual(ram[24:40], bytes(range(8, 24)))

    def test_pair_load_overlapping_destinations(self):
        # Current reference oracle defines second destination write as final.
        s, _ = compare([0xA9400000, RET], {0: BASE + 8})
        self.assertEqual(s.x[0], int.from_bytes(bytes(range(16, 24)), "little"))

    def test_pair_out_of_bounds_has_no_partial_store(self):
        stp = 0xA9000000 | (2 << 10) | 1
        s, ram = compare([stp, RET], {0: BASE + 56})
        self.assertEqual(s.fault, 1)
        self.assertEqual(ram, bytes(range(64)))

    def test_reject_indexed_pair_and_sign_extended(self):
        for invalid in (0xF8408400, 0xB9800000, 0xF8400400):
            with self.subTest(opcode=hex(invalid)):
                self.assertIsNone(translate([invalid, RET]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
