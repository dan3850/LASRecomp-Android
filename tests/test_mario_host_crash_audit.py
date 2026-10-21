"""Pure tests for read-only Mario Termux native-crash symbolization."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_host_crash_audit import parse_text_symbols, closest_symbol


class TestMarioHostCrashAudit(unittest.TestCase):
    def test_symbol_boundaries_and_offsets(self):
        rows = parse_text_symbols(
            "00000000002e0dc0 t internal_renderer\n"
            "00000000002e0e20 T nvn_host_submit\n"
            "00000000002e0e60 D global_data\n"
            "00000000002e0d00 W weak_wrapper\n"
        )
        self.assertEqual(closest_symbol(rows, 0x2e0dfc),
                         ("internal_renderer", 0x2e0dc0, 0x3c))
        self.assertEqual(closest_symbol(rows, 0x2e0e34),
                         ("nvn_host_submit", 0x2e0e20, 0x14))

    def test_does_not_consider_non_code_symbols(self):
        rows = parse_text_symbols(
            "00000100 T fn_a\n"
            "00000110 d data_payload\n"
            "00000120 U imported\n"
            "00000130 t fn_b\n"
        )
        self.assertEqual(closest_symbol(rows, 0x118),
                         ("fn_a", 0x100, 0x18))
        self.assertIsNone(closest_symbol(rows, 0x90))


if __name__ == "__main__":
    unittest.main(verbosity=2)
