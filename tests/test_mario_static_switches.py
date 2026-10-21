"""Mario-only bounded switch recognizer: original-instruction semantic fixtures."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_static_switches import (recognize, recognize_spaced, recognize_masked_guarded,
                                  recognize_guarded_mov_tail, blocks_for_targets,
                                  select_census, select_global_census, valid_selection_mode)


class Insn:
    def __init__(self, address, mnemonic, op_str):
        self.address, self.mnemonic, self.op_str = address, mnemonic, op_str

    def regs_access(self):
        if self.mnemonic == "adds":
            return (), ("w0", "nzcv")
        if self.mnemonic in ("cmp", "b.hi", "bl", "tbz", "br"):
            return (), ()
        return (), (self.op_str.split(",")[0].strip(),)

    def reg_name(self, register):
        return register


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

    def masked_fixture(self):
        # main+0x8ad25c..0x8ad288, rebased to synthetic fixture addresses.
        self.img[0x1030:0x1034] = bytes([0, 2, 10, 26])
        asm = [
            ("cmp", "w26, #3"),
            ("strb", "wzr, [x8, #0x464]"),
            ("b.hi", "#0x70000000f0"),
            ("and", "x10, x26, #0xffffffff"),
            ("adrp", "x13, #0x7000001000"),
            ("add", "x13, x13, #0x30"),
            ("adr", "x12, #0x7000000040"),
            ("ldrb", "w11, [x13, x10]"),
            ("add", "x12, x12, x11, lsl #2"),
            ("ldr", "x11, [sp, #0x48]"),
            ("mov", "w9, #1"),
            ("br", "x12"),
        ]
        return [Insn(self.base + i * 4, mnemonic, operands)
                for i, (mnemonic, operands) in enumerate(asm)]

    def test_masked_guarded_real_mario_jump_table(self):
        code = self.masked_fixture()
        self.assertIsNone(recognize_spaced(code, self.nso, self.base))
        result = recognize_masked_guarded(code, self.nso, self.base)
        self.assertIsNotNone(result)
        self.assertEqual(result["layout"], "masked-index-spaced-br")
        self.assertEqual(result["branch_rva"], 0x2c)
        self.assertEqual(result["table_rva"], 0x1030)
        self.assertEqual(result["targets"], (0x40, 0x48, 0x68, 0xa8))
        self.assertIn(0xa8, result["targets"])

    def test_masked_guarded_rejects_invalid_register_and_branch(self):
        for index, mnemonic, operands in [
            (2, "b.lo", "#0x70000000f0"),
            (3, "and", "x10, x27, #0xffffffff"),
            (7, "ldrb", "w11, [x13, x9]"),
            (8, "add", "x12, x12, x11, lsl #3"),
            (10, "mov", "x12, x0"),
            (11, "br", "x14"),
        ]:
            with self.subTest(index=index, mnemonic=mnemonic):
                code = self.masked_fixture()
                code[index] = Insn(code[index].address, mnemonic, operands)
                self.assertIsNone(recognize_masked_guarded(code, self.nso, self.base))

    def test_masked_guarded_rejects_flag_change_or_out_of_text(self):
        code = self.masked_fixture()
        # A flag-setting instruction between CMP and B.HI invalidates guard.
        code[1] = Insn(code[1].address, "adds", "w0, w0, #1")
        self.assertIsNone(recognize_masked_guarded(code, self.nso, self.base))
        code = self.masked_fixture()
        self.img[0x1033] = 0xff
        self.assertIsNone(recognize_masked_guarded(code, self.nso, self.base))

    def mario_guarded_mov_tail_fixture(self):
        # Same instruction pattern as main+0x9bb5d8..main+0x9bb5f8.
        # In the source log, table_rva=0x107816d; the synthetic 4-byte
        # read-only table contains 0x0b, which maps base+0x40 to +0x6c.
        self.img[0x106d:0x1071] = bytes([0, 11, 19, 33])
        seq = [
            ("cmp", "w8, #3"),
            ("b.hi", "#0x7000000100"),
            ("adrp", "x9, #0x7000001000"),
            ("add", "x9, x9, #0x6d"),
            ("adr", "x10, #0x7000000040"),
            ("ldrb", "w11, [x9, x8]"),
            ("add", "x10, x10, x11, lsl #2"),
            ("mov", "x19, x0"),
            ("br", "x10"),
        ]
        return [Insn(self.base + i * 4, m, op)
                for i, (m, op) in enumerate(seq)]

    def test_mario_9bb628_byte_switch_with_mov_before_branch(self):
        code = self.mario_guarded_mov_tail_fixture()
        result = recognize_guarded_mov_tail(code, self.nso, self.base)
        self.assertIsNotNone(result)
        self.assertEqual(result["layout"], "guarded-neutral-mov-before-br")
        self.assertEqual(result["cases"], 4)
        self.assertEqual(result["table_rva"], 0x106d)
        self.assertEqual(result["branch_rva"], 0x20)
        self.assertIn(0x6c, result["targets"])
        self.assertEqual(result["targets"], (0x40, 0x6c, 0x8c, 0xc4))

    def test_mario_mov_tail_refuses_clobbering_or_wrong_guard(self):
        # Accept only a MOV that preserves the computed BR register.
        for idx, replacement in [
                (7, ("mov", "x10, x0")),
                (7, ("add", "x19, x0, #1")),
                (1, ("b.lo", "#0x7000000100")),
                (5, ("ldrb", "w11, [x9, x7]")),
                (8, ("blr", "x10"))]:
            code = self.mario_guarded_mov_tail_fixture()
            code[idx] = Insn(code[idx].address, *replacement)
            with self.subTest(idx=idx, replacement=replacement):
                self.assertIsNone(
                    recognize_guarded_mov_tail(code, self.nso, self.base))

    def test_mario_mov_tail_refuses_out_of_range_table(self):
        code = self.mario_guarded_mov_tail_fixture()
        self.img[0x106f] = 255
        self.assertIsNone(recognize_guarded_mov_tail(
            code, self.nso, self.base))

    def test_spaced_guarded_switch_observed_mario_layout(self):
        # Reproduces main+0x9b6d60..0x9b6d98: ADRP/ADD x26 precedes
        # several loads, a BL, a TBZ, and the guarded BR x10.
        seq = [
            ("adrp", "x26, #0x7000001000"),
            ("add", "x26, x26, #0x10"),
            ("ldr", "x0, [x20, #0x20]"),
            ("bl", "#0x7000000150"),
            ("tbz", "w0, #0, #0x7000000090"),
            ("add", "w9, w8, w23"),
            ("cmp", "w9, #4"),
            ("b.hi", "#0x7000000090"),
            ("adr", "x10, #0x7000000040"),
            ("ldrb", "w11, [x26, x9]"),
            ("add", "x10, x10, x11, lsl #2"),
            ("br", "x10"),
        ]
        code = [Insn(self.base + 4*i, m, operands)
                for i, (m, operands) in enumerate(seq)]
        self.assertIsNone(recognize(code[-8:], self.nso, self.base))
        found = recognize_spaced(code, self.nso, self.base)
        self.assertIsNotNone(found)
        self.assertEqual(found["layout"], "spaced-table-base")
        self.assertEqual(found["branch_rva"], 0x2c)
        self.assertEqual(found["cases"], 5)
        self.assertEqual(found["targets"], (0x40, 0x48, 0x58, 0x68, 0x88))

    def test_spaced_guarded_switch_refuses_clobbered_table_base(self):
        seq = [
            ("adrp", "x26, #0x7000001000"),
            ("add", "x26, x26, #0x10"),
            ("mov", "x26, x0"),  # invalidates saved table base
            ("bl", "#0x7000000150"),
            ("tbz", "w0, #0, #0x7000000090"),
            ("add", "w9, w8, w23"),
            ("cmp", "w9, #4"),
            ("b.hi", "#0x7000000090"),
            ("adr", "x10, #0x7000000040"),
            ("ldrb", "w11, [x26, x9]"),
            ("add", "x10, x10, x11, lsl #2"),
            ("br", "x10"),
        ]
        code = [Insn(self.base + 4*i, m, operands)
                for i, (m, operands) in enumerate(seq)]
        self.assertIsNone(recognize_spaced(code, self.nso, self.base))
        code[2] = Insn(self.base + 8, "ldr", "x0, [x20]")
        code[7] = Insn(self.base + 28, "b.lo", "#0x7000000090")
        self.assertIsNone(recognize_spaced(code, self.nso, self.base))

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


    def test_cli_modes_global_without_anchor_or_explicit_anchor(self):
        self.assertTrue(valid_selection_mode(True, None))
        self.assertTrue(valid_selection_mode(False, 0x48))
        self.assertFalse(valid_selection_mode(True, 0x48))
        self.assertFalse(valid_selection_mode(False, None))

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
        picked = select_global_census(tables, planned, base, 1, 0x80, 0x40)
        self.assertEqual([b["owner"] for b in picked], [base + 0x40])
        picked = select_global_census(tables, planned, base, 2, 0x80, 0x40)
        self.assertEqual([b["owner"] for b in picked],
                         [base + 0x40, base + 0x80])
        self.assertEqual(select_global_census([], planned, base, 2, 0x80, 0x40), [])



if __name__ == "__main__":
    unittest.main(verbosity=2)
