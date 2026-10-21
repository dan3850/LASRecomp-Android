"""Mario-only bounded switch recognizer: original-instruction semantic fixtures."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_static_switches import recognize, blocks_for_targets, select_census, select_global_census


class Insn:
    def __init__(self, address, mnemonic, op_str):
        self.address, self.mnemonic, self.op_str = address, mnemonic, op_str


class TestMarioStaticSwitch(unittest.TestCase):
    def setUp(self):
        self.base = 0x7000000000
        self.img = bytearray(0x1200)
        self.img[0x1010:0x1015] = bytes([0, 2, 6, 10, 18])
        self.nso = SimpleNamespace(image=self.img, text=(0, 0x200),
                                   rodata=(0x1000, 0x200))
        asm = [
            ("cmp", "w8, #4"),
            ("b.hi", "#0x7000000090"),
            ("adrp", "x9, #0x7000001000"),
            ("add", "x9, x9, #0x10"),
            ("adr", "x10, #0x7000000040"),
            ("ldrb", "w11, [x9, x8]"),
            ("add", "x10, x10, x11, lsl #2"),
            ("br", "x10"),
        ]
        self.code = [Insn(self.base + i * 4, name, args)
                     for i, (name, args) in enumerate(asm)]

    def test_recognizes_all_five_cases_without_emulator(self):
        found = recognize(self.code, self.nso, self.base)
        self.assertIsNotNone(found)
        self.assertEqual(found["branch_rva"], 0x1c)
        self.assertEqual(found["table_rva"], 0x1010)
        self.assertEqual(found["cases"], 5)
        self.assertEqual(found["targets"], (0x40, 0x48, 0x58, 0x68, 0x88))

    def test_rejects_wrong_register_or_missing_guard(self):
        for index, name, arg in [
            (0, "cmp", "w7, #4"),
            (1, "b.lo", "#0x7000000090"),
            (1, "b.hi", "#0x7000000010"),
            (5, "ldrb", "w11, [x19, x8]"),
            (6, "add", "x10, x10, x11, lsl #3"),
            (7, "blr", "x10"),
        ]:
            changed = list(self.code)
            changed[index] = Insn(changed[index].address, name, arg)
            with self.subTest(index=index, arg=arg):
                self.assertIsNone(recognize(changed, self.nso, self.base))

    def test_rejects_table_outside_rodata_and_invalid_target(self):
        changed = list(self.code)
        changed[3] = Insn(changed[3].address, "add", "x9, x9, #0x300")
        self.assertIsNone(recognize(changed, self.nso, self.base))
        self.img[0x1014] = 255
        self.assertIsNone(recognize(self.code, self.nso, self.base))

    def test_groups_by_real_owner_and_preserves_registered_cases(self):
        rows = {
            self.base + 0x40: f"f_{self.base + 0x40:x}",
            self.base + 0x80: f"f_{self.base + 0x80:x}",
            self.base + 0xc0: f"f_{self.base + 0xc0:x}",
            self.base + 0x48: f"mario_resume_{self.base + 0x40:x}",
        }
        targets = (0x40, 0x48, 0x58, 0x68, 0x88)
        planned = blocks_for_targets(targets, rows, self.base, self.base + 0x200)
        self.assertEqual(sorted(planned), [self.base + 0x40, self.base + 0x80])
        self.assertEqual(planned[self.base + 0x40]["targets"],
                         [self.base + 0x58, self.base + 0x68])
        tables = [{"branch_rva": 0x1c, "targets": targets, "cases": 5,
                   "table_rva": 0x1010}]
        blocks, selected = select_census(tables, planned, self.base, 0x58,
                                         2, 0x80, 0x40)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(selected["cases"], 5)
        with self.assertRaisesRegex(ValueError, "budget"):
            select_census(tables, planned, self.base, 0x58, 1, 0x40, 0x40)
        with self.assertRaisesRegex(ValueError, "not in a verified"):
            select_census(tables, planned, self.base, 0x70, 2, 0x80, 0x40)


    def test_global_census_only_selects_complete_verified_tables(self):
        base = self.base
        rows = {
            base + 0x40: f"f_{base + 0x40:x}",
            base + 0x80: f"f_{base + 0x80:x}",
            base + 0xc0: f"f_{base + 0xc0:x}",
        }
        tables = [
            {"branch_rva": 0x1c, "targets": (0x48, 0x88)},
            {"branch_rva": 0x2c, "targets": (0x48,)},
        ]
        planned = blocks_for_targets((0x48, 0x88), rows, base, base + 0x100)
        # Only the small single-owner table fits: no incomplete 2-owner table.
        picked = select_global_census(tables, planned, base, 1, 0x40, 0x40)
        self.assertEqual([b["owner"] for b in picked], [base + 0x40])
        picked = select_global_census(tables, planned, base, 2, 0x80, 0x40)
        self.assertEqual([b["owner"] for b in picked],
                         [base + 0x40, base + 0x80])
        self.assertEqual(select_global_census([], planned, base, 2, 0x80, 0x40), [])



if __name__ == "__main__":
    unittest.main(verbosity=2)
