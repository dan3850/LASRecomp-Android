#!/usr/bin/env python3
"""Synthetic, no-ROM tests for the limited Mario ARM64 leaf recompiler.

Run: python3 tests/test_mario_leaf_codegen.py
Requires clang for native generated-C execution tests.
"""
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mario_leaf_codegen import HEADER, translate


def mov_wide(op, reg, imm, hw=0, width=64):
    base = {"movn": 0x12800000, "movz": 0x52800000,
            "movk": 0x72800000}[op]
    return base | (0x80000000 if width == 64 else 0) | (hw << 21) | (imm << 5) | reg


def add_imm(dest, src, imm, *, sub=False, width=64):
    base = 0x51000000 if sub else 0x11000000
    return base | (0x80000000 if width == 64 else 0) | (imm << 10) | (src << 5) | dest


RET = 0xD65F03C0


class State(ctypes.Structure):
    _fields_ = [("x", ctypes.c_uint64 * 31), ("sp", ctypes.c_uint64),
                ("pc", ctypes.c_uint64), ("nzcv", ctypes.c_uint64),
                ("mem", ctypes.POINTER(ctypes.c_uint8)),
                ("mem_base", ctypes.c_uint64), ("mem_size", ctypes.c_uint64),
                ("fault", ctypes.c_uint64)]


class TestMarioCodegen(unittest.TestCase):
    def test_reject_unsupported_and_early_ret(self):
        for words in ([RET, RET], [0x14000000, RET], [0xF8400400, RET],
                      [0x14000001, RET], [0x52800000 | (2 << 21), RET]):
            with self.subTest(words=words):
                self.assertIsNone(translate(words))

    def test_reject_missing_ret(self):
        self.assertIsNone(translate([add_imm(0, 0, 1)]))

    def test_forward_conditional_branches(self):
        cbz = 0xB4000000 | (2 << 5) | 0
        cbnz = 0xB5000000 | (2 << 5) | 7
        self.assertIsNotNone(translate([cbz, add_imm(0, 0, 1), RET]))
        self.assertIsNotNone(translate([cbnz, add_imm(0, 0, 1), RET]))
        self.assertIsNone(translate([0xB4000000, RET]))  # backward/self
        self.assertIsNone(translate([0xB4000000 | (3 << 5), RET]))  # outside

    def test_bcond_validity(self):
        for cond in range(14):
            word = 0x54000000 | (2 << 5) | cond
            self.assertIsNotNone(translate([word, add_imm(0, 0, 1), RET]))
        for cond in (14, 15):
            self.assertIsNone(translate([0x54000000 | (2 << 5) | cond, RET]))
        self.assertIsNone(translate([0x54000000, RET]))
        self.assertIsNone(translate([0x54000000 | (3 << 5), RET]))

    def test_cmp_subs_flags_translation(self):
        # CMP W0,#10 ; B.EQ +2 ; ADD X1,X1,#1 ; RET
        cmp_w = 0x7100001F | (10 << 10)
        beq = 0x54000000 | (2 << 5)
        self.assertIsNotNone(translate([cmp_w, beq, add_imm(1, 1, 1), RET]))
        # SUBS X2,X0,#1; 32-bit ADDS W3,W3,#1
        self.assertIsNotNone(translate([0xF1000402, 0x31000463, RET]))
        # Reserved shift
        self.assertIsNone(translate([0x7100001F | (2 << 22), RET]))

    @unittest.skipUnless(shutil.which("clang"), "Clang required for NZCV native tests")
    def test_nzcv_native_edge_cases_and_branches(self):
        # Independent expected results, including unsigned carry and signed overflow.
        cases = [
            (32, False, 0xFFFFFFFF, 1, 0x0, 0x60000000),
            (32, False, 0x7FFFFFFF, 1, 0x80000000, 0x90000000),
            (32, True, 0, 1, 0xFFFFFFFF, 0x80000000),
            (32, True, 0x80000000, 1, 0x7FFFFFFF, 0x30000000),
            (64, False, 0xFFFFFFFFFFFFFFFF, 1, 0, 0x60000000),
            (64, False, 0x7FFFFFFFFFFFFFFF, 1, 0x8000000000000000, 0x90000000),
            (64, True, 0, 1, 0xFFFFFFFFFFFFFFFF, 0x80000000),
            (64, True, 0x8000000000000000, 1, 0x7FFFFFFFFFFFFFFF, 0x30000000),
            (64, True, 10, 10, 0, 0x60000000),
            (64, True, 9, 10, 0xFFFFFFFFFFFFFFFF, 0x80000000),
        ]
        generated = [HEADER]
        for i, (width, subtract, _, immediate, _, _) in enumerate(cases):
            opcode = (0x71000000 if subtract else 0x31000000)
            if width == 64:
                opcode |= 0x80000000
            opcode |= immediate << 10
            statements = translate([opcode, RET])
            self.assertIsNotNone(statements)
            generated.extend([f"void flags_{i}(MarioA64State *s) {{",
                              *statements, "}"])
        # CMP X0,#10 ; B.EQ skip ADD X1,#1 ; RET
        branch_words = [0xF100281F, 0x54000040, add_imm(1, 1, 1), RET]
        statements = translate(branch_words)
        self.assertIsNotNone(statements)
        generated.extend(["void cmp_branch(MarioA64State *s) {", *statements, "}"])
        with tempfile.TemporaryDirectory(prefix="mario-nzcv-") as tmp:
            source, library = Path(tmp) / "flags.c", Path(tmp) / "flags.so"
            source.write_text("\n".join(generated) + "\n", encoding="utf-8")
            subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                           check=True)
            lib = ctypes.CDLL(str(library))
            for i, (_, _, operand, _, expected_result, expected_flags) in enumerate(cases):
                with self.subTest(case=i):
                    state = State()
                    state.x[0] = operand
                    state.x[30] = 0x12345678
                    fn = getattr(lib, f"flags_{i}")
                    fn.argtypes = [ctypes.POINTER(State)]
                    fn(ctypes.byref(state))
                    self.assertEqual(state.x[0], expected_result)
                    self.assertEqual(state.nzcv, expected_flags)
                    self.assertEqual(state.pc, 0x12345678)
            for operand, expected_x1 in ((10, 0), (9, 1)):
                state = State()
                state.x[0] = operand
                state.x[30] = 0x12345678
                fn = lib.cmp_branch
                fn.argtypes = [ctypes.POINTER(State)]
                fn(ctypes.byref(state))
                self.assertEqual(state.x[1], expected_x1)
                self.assertEqual(state.nzcv, 0x60000000 if operand == 10 else 0x80000000)

    def test_supported_translation(self):
        self.assertIsNotNone(translate([add_imm(0, 0, 0x180), RET]))
        self.assertIsNotNone(translate([add_imm(31, 31, 16), RET]))
        self.assertIsNotNone(translate([mov_wide("movz", 2, 0x1234, width=32), RET]))
        self.assertIsNotNone(translate([0xF9400000, RET]))  # LDR X0, [X0]

    @unittest.skipUnless(shutil.which("clang"), "Clang required for generated C tests")
    def test_native_semantics_all_registers_and_sp(self):
        tests = [
            ([add_imm(0, 0, 0x180), RET], {0: 0x180}),
            ([add_imm(0, 0, 0x1A0), RET], {0: 0x1A0}),
            ([add_imm(31, 31, 16), add_imm(0, 31, 32), RET], {0: 0x100030}),
            ([mov_wide("movz", 2, 0x1234),
              mov_wide("movk", 2, 0xabcd, hw=1), RET], {2: 0xabcd1234}),
            ([mov_wide("movn", 3, 0), RET], {3: 0xFFFFFFFFFFFFFFFF}),
            ([mov_wide("movz", 4, 0xffff, hw=1, width=32), RET], {4: 0xFFFF0000}),
            ([mov_wide("movn", 5, 0, width=32), RET], {5: 0xFFFFFFFF}),
            ([mov_wide("movk", 6, 0x0, hw=1, width=32), RET], {6: 0x7777}),
            ([add_imm(7, 7, 1, width=32), RET], {7: 0}),
            ([add_imm(8, 8, 2, sub=True), RET], {8: 0x7775}),
            ([mov_wide("movz", 31, 0xffff), RET], {}),
            ([0xB4000000 | (2 << 5), add_imm(0, 0, 1), RET], {0: 0}),
            ([0xB5000000 | (2 << 5) | 7, add_imm(7, 7, 1), RET], {7: 0xFFFFFFFF}),
            ([0x54000000 | (2 << 5) | 2, add_imm(0, 0, 1), RET], {0: 0}),
            ([0x54000000 | (2 << 5) | 0, add_imm(0, 0, 1), RET], {0: 1}),
        ]
        with tempfile.TemporaryDirectory(prefix="test-mario-leaf-") as tmp:
            cfile = Path(tmp) / "leaves.c"
            sofile = Path(tmp) / "leaves.so"
            contents = [HEADER]
            for i, (words, _) in enumerate(tests):
                statements = translate(words)
                self.assertIsNotNone(statements, i)
                contents.append(f"void test_{i}(MarioA64State *s) {{")
                contents.extend(statements)
                contents.append("}")
            cfile.write_text("\n".join(contents), encoding="utf-8")
            subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                            "-Wall", "-Wextra", "-Werror", str(cfile), "-o", str(sofile)],
                           check=True)
            lib = ctypes.CDLL(str(sofile))
            for i, (_, changed) in enumerate(tests):
                with self.subTest(function=i):
                    state = State()
                    for reg in range(31):
                        state.x[reg] = 0x7777
                    state.x[0] = 0
                    state.x[7] = 0xFFFFFFFF
                    state.x[30] = 0x20100000
                    state.sp = 0x100000
                    state.nzcv = 0xA0000000
                    state.pc = 0x10000000
                    if i == 7:
                        state.x[6] = 0xABCDEF0077777777
                    original = tuple(state.x)
                    fn = getattr(lib, f"test_{i}")
                    fn.argtypes = [ctypes.POINTER(State)]
                    fn(ctypes.byref(state))
                    for reg in range(31):
                        self.assertEqual(state.x[reg], changed.get(reg, original[reg]), f"test {i} x{reg}")
                    self.assertEqual(state.sp, 0x100010 if i == 2 else 0x100000)
                    self.assertEqual(state.pc, 0x20100000)
                    self.assertEqual(state.nzcv, 0xA0000000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
