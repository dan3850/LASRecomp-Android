"""Diagnostic-only ranking: no patched instructions may be emitted for execution."""
from pathlib import Path
import sys
import unittest

import capstone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_fde_priorities import inspect_candidate, NOP, RET


class TestMarioFdePriorities(unittest.TestCase):
    def setUp(self):
        self.md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)

    def test_single_missing_family_nop_proxy(self):
        words = [0x90000000, RET]  # ADRP X0, #0
        original = words.copy()
        missing, rescued, samples = inspect_candidate(words, 0x1000, self.md)
        self.assertEqual(missing, {"adrp"})
        self.assertEqual(rescued, {"adrp"})
        self.assertEqual(samples["adrp"], (0x1000, 0x90000000))
        self.assertEqual(words, original)  # Diagnostic must not mutate guest code

    def test_two_missing_families_not_rescued(self):
        words = [0x90000000, 0xD61F0000, RET]  # ADRP, BR X0, RET
        missing, rescued, _ = inspect_candidate(words, 0x1000, self.md)
        self.assertEqual(missing, {"adrp", "br"})
        self.assertEqual(rescued, set())

    def test_supported_opcodes_not_ranked(self):
        words = [0x91000400, NOP, RET]  # ADD X0,X0,#1
        missing, rescued, _ = inspect_candidate(words, 0x1000, self.md)
        self.assertEqual(missing, set())
        self.assertEqual(rescued, set())

    def test_rejecting_branch_is_structural_not_missing_mnemonic(self):
        words = [0x14000000, RET]  # B to self (backward/nonforward)
        missing, rescued, _ = inspect_candidate(words, 0x1000, self.md)
        self.assertEqual(missing, set())
        self.assertEqual(rescued, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
