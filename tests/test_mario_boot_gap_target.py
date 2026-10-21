"""Pure, read-only tests for Mario missing-PC instruction window bounds."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_boot_gap_audit import target_window_bounds


class MarioGapTargetWindowTests(unittest.TestCase):
    def test_window_includes_local_return_site_and_target(self):
        begin, end = target_window_bounds(0, 0x1000000, 0x9b6ddc, 0x9b6d78)
        self.assertLessEqual(begin, 0x9b6d74)
        self.assertLessEqual(begin, 0x9b6ddc)
        self.assertGreater(end, 0x9b6ddc)

    def test_clamps_to_executable_segment(self):
        self.assertEqual(target_window_bounds(0x1000, 0x100, 0x1000),
                         (0x1000, 0x1040))
        self.assertEqual(target_window_bounds(0x1000, 0x100, 0x10fc),
                         (0x105c, 0x1100))

    def test_rejects_unaligned_or_outside_target(self):
        for pc in (0x1001, 0x0ffc, 0x1100):
            with self.subTest(pc=pc):
                with self.assertRaises(ValueError):
                    target_window_bounds(0x1000, 0x100, pc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
