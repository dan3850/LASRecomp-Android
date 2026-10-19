#!/usr/bin/env python3
"""LDP/STP signed-offset guest semantics; compile generated C on Termux."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_mario_memory_codegen import compare, BASE, RET
from mario_leaf_codegen import translate


def pair(load, width, rt, rt2, rn, offset=0):
    if offset % width or not -64 <= offset // width <= 63:
        raise ValueError("invalid signed scaled pair offset")
    base = {(False, 4): 0x29000000, (True, 4): 0x29400000,
            (False, 8): 0xA9000000, (True, 8): 0xA9400000}[(load, width)]
    return (base | ((offset // width & 127) << 15)
            | (rt2 << 10) | (rn << 5) | rt)


class TestPairMemory(unittest.TestCase):
    def test_x_pair_roundtrip(self):
        words = [pair(False, 8, 1, 2, 0), pair(True, 8, 3, 4, 0), RET]
        s, mem = compare(words, {0: BASE + 16, 1: 0x0123456789ABCDEF,
                                  2: 0xFEDCBA9876543210})
        self.assertEqual(s.x[3], 0x0123456789ABCDEF)
        self.assertEqual(s.x[4], 0xFEDCBA9876543210)
        self.assertEqual(mem[16:24], bytes.fromhex("efcdab8967452301"))

    def test_w_pair_zero_extends(self):
        words = [pair(False, 4, 1, 2, 0), pair(True, 4, 3, 4, 0), RET]
        s, _ = compare(words, {0: BASE + 16, 1: 0xABCDEF0012345678,
                                2: 0xFFEEDDCCBBAA9988})
        self.assertEqual(s.x[3], 0x12345678)
        self.assertEqual(s.x[4], 0xBBAA9988)

    def test_sp_negative_offset(self):
        words = [pair(False, 8, 1, 2, 31, -16),
                 pair(True, 8, 3, 4, 31, -16), RET]
        s, _ = compare(words, {1: 0x0123456789ABCDEF, 2: 0x1122334455667788})
        self.assertEqual(s.x[3], 0x0123456789ABCDEF)
        self.assertEqual(s.x[4], 0x1122334455667788)
        self.assertEqual(s.sp, BASE + 16)

    def test_zero_register(self):
        words = [pair(False, 8, 31, 1, 0),
                 pair(True, 8, 31, 2, 0), RET]
        s, mem = compare(words, {0: BASE + 16, 1: 0xAABBCCDDEEFF0011})
        self.assertEqual(mem[16:24], bytes(8))
        self.assertEqual(s.x[2], 0xAABBCCDDEEFF0011)

    def test_overlapping_destinations(self):
        words = [pair(True, 8, 2, 2, 0), RET]
        s, _ = compare(words, {0: BASE + 16})
        self.assertEqual(s.x[2], int.from_bytes(bytes(range(24, 32)), "little"))

    def test_out_of_bounds_pair_does_not_partially_write(self):
        s, mem = compare([pair(False, 8, 1, 2, 0), RET],
                         {0: BASE + 56}, size=64)
        self.assertEqual(s.fault, 1)
        self.assertEqual(mem, bytes(range(64)))

    def test_unsupported_pre_post_index_and_simd(self):
        for word in (0xA9800000, 0xA8800000, 0xA8C00000, 0xAD000000):
            with self.subTest(opcode=hex(word)):
                self.assertIsNone(translate([word, RET]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
