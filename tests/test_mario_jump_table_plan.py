"""Synthetic jump-table case coverage for Mario; no Nintendo code or game files."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mario_jump_table_plan import plan


class TestMarioJumpTablePlan(unittest.TestCase):
    def setUp(self):
        self.base = 0x7000000000
        image = bytearray(0x200)
        image[0x110:0x116] = bytes([0, 12, 8, 5, 10, 16])
        self.nso = SimpleNamespace(
            image=image, text=(0, 0x80), rodata=(0x100, 0x100))

    def test_observed_interior_case_and_all_other_case_entries(self):
        cases, missing, raw = plan(
            self.nso, self.base,
            {self.base + 0x10, self.base + 0x40},
            0x110, 0x10, 6, observed_index=1,
            observed_target_rva=0x40, observed_byte=12)
        self.assertEqual(cases, [0x10, 0x40, 0x30, 0x24, 0x38, 0x50])
        self.assertEqual(missing, [0x24, 0x30, 0x38, 0x50])
        self.assertEqual(raw, bytes([0, 12, 8, 5, 10, 16]))

    def test_no_case_is_repaired_if_all_registered(self):
        registered = {self.base + off for off in (0x10, 0x40, 0x30, 0x24, 0x38, 0x50)}
        _, missing, _ = plan(
            self.nso, self.base, registered, 0x110, 0x10, 6,
            observed_index=1, observed_target_rva=0x40)
        self.assertEqual(missing, [])

    def test_detect_mismatched_observed_branch(self):
        with self.assertRaisesRegex(ValueError, "logged target mismatch"):
            plan(self.nso, self.base, set(), 0x110, 0x10, 6,
                 observed_index=1, observed_target_rva=0x44)
        with self.assertRaisesRegex(ValueError, "observed LDRB byte"):
            plan(self.nso, self.base, set(), 0x110, 0x10, 6,
                 observed_index=1, observed_target_rva=0x40, observed_byte=11)

    def test_reject_unbounded_or_non_rodata_tables(self):
        with self.assertRaisesRegex(ValueError, "count"):
            plan(self.nso, self.base, set(), 0x110, 0x10, 65,
                 observed_index=1, observed_target_rva=0x40)
        with self.assertRaisesRegex(ValueError, "outside original rodata"):
            plan(self.nso, self.base, set(), 0x30, 0x10, 6,
                 observed_index=1, observed_target_rva=0x40)

    def test_reject_invalid_guest_targets(self):
        with self.assertRaisesRegex(ValueError, "outside aligned executable text"):
            plan(self.nso, self.base, set(), 0x110, 0x70, 6,
                 observed_index=1, observed_target_rva=0xa0)


if __name__ == "__main__":
    unittest.main()
