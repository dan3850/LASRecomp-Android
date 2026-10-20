"""Synthetic checks for Mario read-only dispatch/relocation coverage; no game data."""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import mario_boot_gap_audit as audit
from nso import R_AARCH64_ABS64, R_AARCH64_GLOB_DAT, R_AARCH64_JUMP_SLOT, R_AARCH64_RELATIVE


class TestGuestGapAudit(unittest.TestCase):
    def test_static_local_code_targets_and_symbol_resolution(self):
        nso = SimpleNamespace(
            text=(0, 0x80),
            syms=[("local", 0x12, 1, 0x20, 4),
                  ("import", 0x12, 0, 0, 4)],
            relocs=[
                (0x100, R_AARCH64_RELATIVE, 0, 0x18),
                (0x108, R_AARCH64_ABS64, 0, 0x18),
                (0x110, R_AARCH64_GLOB_DAT, 0, 0x10),
                (0x118, R_AARCH64_JUMP_SLOT, 0, 0x14),
                (0x120, R_AARCH64_ABS64, 1, 0x10),  # imported symbol excluded
                (0x128, R_AARCH64_ABS64, 3, 0x10),  # bad index excluded
                (0x130, R_AARCH64_RELATIVE, 0, 0x81),  # unaligned/outside
                (0x138, 9999, 0, 0x28),  # unsupported relocation excluded
            ])
        self.assertEqual(
            list(audit.local_code_relocation_targets(nso)),
            [(0x18, 0x100, R_AARCH64_RELATIVE),
             (0x38, 0x108, R_AARCH64_ABS64),
             (0x30, 0x110, R_AARCH64_GLOB_DAT),
             (0x34, 0x118, R_AARCH64_JUMP_SLOT)])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            audit.relocation_census("main", nso, 0x7000000000,
                                   [0x7000000010, 0x7000000030],
                                   [0x7000000010, 0x7000000028],
                                   [0x18, 0x4c])
        self.assertIn("4 distinct local relocation targets", stdout.getvalue())
        self.assertIn("3 without an exact dispatcher entry", stdout.getvalue())
        self.assertIn("main+0x18: 1 relocation(s)", stdout.getvalue())
        self.assertIn("main+0x4c: not present", stdout.getvalue())

    def test_address_provenance_cannot_guess_missing_source(self):
        self.assertEqual(audit.owner([0x7000000010, 0x7000000028], 0x7000000024),
                         0x7000000010)
        self.assertIsNone(audit.owner([0x7000000010], 0x700000000c))
        self.assertEqual(audit.instruction_kind(0xd63f0100), "BLR indirect call")
        self.assertEqual(audit.instruction_kind(0xd65f03c0), "RET")

    def test_generated_table_is_sorted_and_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main_table.c"
            path.write_text(
                "void f_7000000010(Cpu *c);\n"
                "void f_7000000028(Cpu *c);\n"
                "const uint64_t main_fn_addrs[] = {\n"
                "0x7000000010ull,\n0x7000000020ull,\n0x7000000028ull};\n")
            # Parser expects only the hex address tokens from the C table.
            entries, starts = audit.parse_table(path, "main")
            self.assertEqual(entries, [0x7000000010, 0x7000000020, 0x7000000028])
            self.assertEqual(starts, [0x7000000010, 0x7000000028])


if __name__ == "__main__":
    unittest.main()
