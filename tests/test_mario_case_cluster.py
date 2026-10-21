"""Mario-only case-cluster census: explicit AArch64 control-flow fixtures."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_case_cluster import b_imm_target, clustered_cases, select_case_owners


class MarioCaseClusterTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x7000000000
        self.join = self.base + 0x524
        self.sites = [self.base + x for x in
                      (0x1bc, 0x1cc, 0x1dc, 0x1ec, 0x204, 0x218, 0x254)]
        self.rows = {
            self.base + 0x180: f"f_{self.base + 0x180:x}",
            self.base + 0x1ac: f"f_{self.base + 0x1ac:x}",
            self.base + 0x380: f"f_{self.base + 0x380:x}",
        }

    def test_arm64_unconditional_b_signed(self):
        pc = self.base + 0x218
        forward = 0x14000000 | ((self.join - pc) // 4)
        self.assertEqual(b_imm_target(pc, forward), self.join)
        self.assertEqual(b_imm_target(pc, 0x14000000 | 0x03ffffff), pc - 4)
        self.assertIsNone(b_imm_target(pc, 0x94000000))
        self.assertIsNone(b_imm_target(pc, 0xd61f0180))

    def test_detects_case_start_immediately_after_repeated_b(self):
        branches = [(site, self.join) for site in self.sites]
        found = clustered_cases(branches, lo=self.base, hi=self.base + 0x1000)
        self.assertIn(self.base + 0x21c, found)
        join, sources = found[self.base + 0x21c]
        self.assertEqual(join, self.join)
        self.assertEqual(len(sources), len(self.sites))

    def test_picks_entire_owner_with_budget_and_neighbor_cases(self):
        cases = clustered_cases(
            [(pc, self.join) for pc in self.sites],
            lo=self.base, hi=self.base + 0x1000)
        chosen = select_case_owners(
            cases, self.rows, self.base, self.base + 0x1000,
            observed=self.base + 0x21c, limit=1,
            budget_bytes=0x400, max_block_bytes=0x400)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]["owner"], self.base + 0x1ac)
        self.assertIn(self.base + 0x21c, chosen[0]["cases"])
        self.assertGreater(len(chosen[0]["cases"]), 3)

    def test_rejects_unproven_target_and_inadequate_budget(self):
        cases = clustered_cases(
            [(pc, self.join) for pc in self.sites],
            lo=self.base, hi=self.base + 0x1000)
        with self.assertRaisesRegex(ValueError, "not a validated B\\+4"):
            select_case_owners(
                cases, self.rows, self.base, self.base + 0x1000,
                observed=self.base + 0x224)
        with self.assertRaisesRegex(ValueError, "byte budget"):
            select_case_owners(
                cases, self.rows, self.base, self.base + 0x1000,
                observed=self.base + 0x21c, limit=1,
                budget_bytes=128, max_block_bytes=0x400)

    def test_no_cluster_for_two_or_unrelated_branches(self):
        self.assertEqual(clustered_cases(
            [(self.base + 0x218, self.join),
             (self.base + 0x204, self.join)],
            lo=self.base, hi=self.base + 0x1000), {})
        self.assertEqual(clustered_cases(
            [(pc, self.base + 0x700 + i * 4)
             for i, pc in enumerate(self.sites)],
            lo=self.base, hi=self.base + 0x1000), {})
        self.assertEqual(clustered_cases(
            [(pc, self.base + 0x100)
             for pc in self.sites],
            lo=self.base, hi=self.base + 0x1000), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
