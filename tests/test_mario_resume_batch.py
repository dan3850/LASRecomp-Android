#!/usr/bin/env python3
"""Source-only regression tests for proactive Mario batch reentry planning."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_resume_batch import parse_anchors, select_blocks


class MarioBatchTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x7000000000
        self.rows = {
            self.base + offset: f"f_{self.base + offset:x}"
            for offset in (0, 0x40, 0x80, 0xc0, 0x100)
        }
        # Function 0x80 contains BR X9 and 0xc0 contains BLR X10.
        self.words = {
            self.base + 0x84: 0xD61F0120,
            self.base + 0xc4: 0xD63F0140,
        }

    def plan(self, anchors=(0x48,), **kwargs):
        return select_blocks(
            self.rows, self.base, self.base + 0x140,
            anchors, lambda pc: self.words.get(pc, 0xd503201f),
            **kwargs
        )

    def test_anchor_first_and_indirect_neighbor(self):
        blocks = self.plan(limit=2, budget_bytes=0x80)
        self.assertEqual([b["offset"] for b in blocks], [0x48, 0x84])
        self.assertTrue(blocks[0]["forced"])
        self.assertTrue(blocks[1]["indirect"])

    def test_plain_neighbors_are_not_expanded_speculatively(self):
        self.words.clear()
        blocks = self.plan(limit=8)
        self.assertEqual([b["offset"] for b in blocks], [0x48])

    def test_local_cohort_can_include_destinations_without_br(self):
        # A computed call originates in the caller, not in its destination.
        self.words.clear()
        blocks = self.plan(
            limit=4, budget_bytes=0x100, nearby_radius=0x80
        )
        self.assertEqual(
            [b["offset"] for b in blocks],
            [0x48, 0x04, 0x84, 0xc4]
        )
        self.assertTrue(all(b["nearby"] or b["forced"] for b in blocks))

    def test_cohort_radius_is_bounded(self):
        self.words.clear()
        blocks = self.plan(limit=8, nearby_radius=0x40)
        self.assertEqual(
            [b["offset"] for b in blocks],
            [0x48, 0x04, 0x84]
        )
        with self.assertRaisesRegex(ValueError, "invalid repair planning"):
            self.plan(nearby_radius=0x100, radius=0x40)

    def test_two_observed_targets_take_priority(self):
        self.words.clear()
        blocks = self.plan(
            anchors=(0x48, 0x88), limit=2,
            budget_bytes=0x80, nearby_radius=0x80
        )
        self.assertEqual(
            [b["offset"] for b in blocks],
            [0x48, 0x88]
        )

    def test_previously_expanded_block_is_not_rebuilt(self):
        owner = self.base + 0x80
        for pc in range(owner + 4, self.base + 0xc0, 4):
            self.rows[pc] = f"mario_resume_{owner:x}"
        self.assertNotIn(0x84, [b["offset"] for b in self.plan()])

    def test_limits_preserve_current_observed_failure(self):
        blocks = self.plan(limit=1, budget_bytes=0x40)
        self.assertEqual([b["offset"] for b in blocks], [0x48])
        with self.assertRaisesRegex(ValueError, "byte budget"):
            self.plan(limit=1, budget_bytes=0x20)

    def test_oversized_observed_block_rejected(self):
        self.rows = {self.base: f"f_{self.base:x}"}
        with self.assertRaisesRegex(ValueError, "oversized block"):
            self.plan(max_block_bytes=0x40)

    def test_malformed_and_unaligned_anchor(self):
        self.assertEqual(parse_anchors(["main:0x48", "sdk:0x88"]),
                         {"main": [0x48], "sdk": [0x88]})
        with self.assertRaisesRegex(ValueError, "unaligned"):
            parse_anchors(["main:0x45"])
        with self.assertRaisesRegex(ValueError, "anchor must"):
            parse_anchors(["main:85"])

    def test_previously_registered_observed_address(self):
        self.rows[self.base + 0x48] = f"mario_resume_{self.base + 0x40:x}"
        blocks = self.plan(limit=2)
        self.assertTrue(all(not b["forced"] for b in blocks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
