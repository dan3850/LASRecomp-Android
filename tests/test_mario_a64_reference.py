#!/usr/bin/env python3
"""Independent guest AArch64 subset interpreter tests; no game image required."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_a64_reference import run_reference


def state():
    regs = [0x7777] * 31
    regs[0] = 0x1000
    regs[30] = 0x20000000
    return SimpleNamespace(x=regs, sp=0x100000, nzcv=0xA0000000)


def run(words, s=None):
    return run_reference(struct.pack("<" + "I" * len(words), *words), s or state())


RET = 0xD65F03C0
NOP = 0xD503201F


def wide(op, dest, imm, *, shift=0, bits=64):
    base = {"movn": 0x12800000, "movz": 0x52800000,
            "movk": 0x72800000}[op]
    return base | (0x80000000 if bits == 64 else 0) | ((shift // 16) << 21) | (imm << 5) | dest


def arithmetic(dest, src, amount, *, bits=64, sub=False):
    base = 0x51000000 if sub else 0x11000000
    return base | (0x80000000 if bits == 64 else 0) | (amount << 10) | (src << 5) | dest


class TestMarioReference(unittest.TestCase):
    def test_mario_add_examples(self):
        for immediate in (0x180, 0x1A0):
            with self.subTest(immediate=immediate):
                regs, sp, pc, flags = run([arithmetic(0, 0, immediate), RET])
                self.assertEqual(regs[0], 0x1000 + immediate)
                self.assertEqual(regs[1], 0x7777)
                self.assertEqual(sp, 0x100000)
                self.assertEqual(pc, 0x20000000)
                self.assertEqual(flags, 0xA0000000)

    def test_32bit_registers_zero_extend(self):
        s = state()
        s.x[4] = 0xFFFFFFFFFFFFFFFF
        regs, *_ = run([arithmetic(4, 4, 1, bits=32), RET], s)
        self.assertEqual(regs[4], 0)

    def test_sp_behavior(self):
        regs, sp, pc, _ = run([arithmetic(31, 31, 16),
                               arithmetic(0, 31, 32), RET])
        self.assertEqual(sp, 0x100010)
        self.assertEqual(regs[0], 0x100030)
        self.assertEqual(pc, 0x20000000)

    def test_movz_movk_movn(self):
        regs, *_ = run([wide("movz", 2, 0x1234),
                         wide("movk", 2, 0xABCD, shift=16),
                         wide("movn", 3, 0),
                         wide("movz", 5, 0xFFFF, shift=16, bits=32), RET])
        self.assertEqual(regs[2], 0xABCD1234)
        self.assertEqual(regs[3], 0xFFFFFFFFFFFFFFFF)
        self.assertEqual(regs[5], 0xFFFF0000)

    def test_reject_unknown_and_early_ret(self):
        for words in ([0xFFFFFFFF, RET], [RET, NOP], [NOP]):
            with self.subTest(words=words):
                with self.assertRaises(ValueError):
                    run(words)


if __name__ == "__main__":
    unittest.main(verbosity=2)
