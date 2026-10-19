"""Native differential tests for opt-in bounded ARM64 backward branches.

Covers backward B, B.cond, CBZ/CBNZ and TBZ/TBNZ; true infinite loops
must stop with guest fault code 2 after the same instruction count as the
independent Python interpreter. No game binary is needed.
"""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mario_leaf_codegen import HEADER, translate
from mario_a64_reference import InstructionLimitExceeded, run_reference
from mario_leaf_verify import State, run_original, snapshot

RET = 0xD65F03C0
SUB_X0_1 = 0xD1000400
SUBS_X0_1 = 0xF1000400
ADD_X0_1 = 0x91000400
ADD_W1_1 = 0x11000421
STRB_W1_X0 = 0x39000001
BASE = 0x30000000
BUDGET = 64


def b(delta):
    return 0x14000000 | (delta & 0x03FFFFFF)


def cb(delta, rt=0, nonzero=False, wide=True):
    return (0x34000000 | (int(wide) << 31) | (int(nonzero) << 24) |
            ((delta & 0x7FFFF) << 5) | rt)


def conditional(delta, cond):
    return 0x54000000 | ((delta & 0x7FFFF) << 5) | cond


def testbit(delta, bit, nonzero=False, rt=0):
    return (0x36000000 | ((bit >> 5) << 31) | (int(nonzero) << 24) |
            ((bit & 31) << 19) | ((delta & 0x3FFF) << 5) | rt)


class TestBoundedLoops(unittest.TestCase):
    def test_opt_in_and_bad_targets(self):
        loop = [SUB_X0_1, cb(-1, nonzero=True), RET]
        self.assertIsNone(translate(loop))
        self.assertIsNotNone(translate(loop, allow_backward_branches=True))
        self.assertIsNone(translate([b(-1), RET]))
        self.assertIsNotNone(translate([b(0), RET], allow_backward_branches=True))
        self.assertIsNone(translate([b(-1), RET], allow_backward_branches=True))
        self.assertIsNone(translate([b(3), RET], allow_backward_branches=True))
        self.assertIsNone(translate([b(0), RET], allow_backward_branches=True, max_steps=0))
        self.assertIsNone(translate([conditional(-1, 14), RET],
                                    allow_backward_branches=True))
        state = State()
        state.x[0] = 1
        code = struct.pack("<3I", *loop)
        with self.assertRaises(ValueError):
            run_reference(code, state)
        with self.assertRaises(ValueError):
            run_reference(code, state, allow_backward_branches=True, max_steps=0)

    def test_verifier_reports_timeout_distinct_from_guest_memory_fault(self):
        state = State()
        state.x[30] = 0x20000000
        state.pc = 0x10000000
        guest = struct.pack("<2I", b(0), RET)
        result, memory, fault_code = run_original(
            guest, state, allow_backward_branches=True, max_steps=8)
        self.assertIsNone(result)
        self.assertIsNone(memory)
        self.assertEqual(fault_code, 2)

    @unittest.skipUnless(shutil.which("clang"), "clang required")
    def test_bounded_native_loops_and_memory(self):
        scenarios = [
            ("b_with_cbz_exit", [cb(3), SUB_X0_1, b(-2), RET], (0, 1, 3, 5)),
            ("cbnz_countdown", [SUB_X0_1, cb(-1, nonzero=True), RET], (1, 2, 3, 4)),
            ("bne_countdown", [SUBS_X0_1, conditional(-1, 1), RET], (1, 2, 3, 4)),
            ("tbnz_bit0", [SUB_X0_1, testbit(-1, 0, nonzero=True), RET], (1, 2, 3, 4)),
            ("tbz_bit2", [ADD_X0_1, testbit(-1, 2), RET], (0, 1, 2, 3)),
            ("self_loop_timeout", [b(0), RET], (0, 1)),
            ("countdown_timeout", [SUB_X0_1, cb(-1, nonzero=True), RET], (0,)),
            ("memory_loop_timeout",
             [STRB_W1_X0, ADD_W1_1, b(-2), RET], (0,)),
        ]
        with tempfile.TemporaryDirectory(prefix="mario-loop-") as tmp:
            source, library = Path(tmp) / "loop.c", Path(tmp) / "loop.so"
            fragments = [HEADER]
            for index, (_, words, _) in enumerate(scenarios):
                body = translate(words, allow_backward_branches=True,
                                 max_steps=BUDGET)
                self.assertIsNotNone(body, (index, words))
                fragments += [f"void case_{index}(MarioA64State *s) {{", *body, "}"]
            source.write_text("\n".join(fragments) + "\n", encoding="utf-8")
            subprocess.run(["clang", "-std=c11", "-O2", "-shared", "-fPIC",
                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                           check=True, capture_output=True)
            dll = ctypes.CDLL(str(library))
            for index, (name, words, values) in enumerate(scenarios):
                fn = getattr(dll, f"case_{index}")
                fn.argtypes = [ctypes.POINTER(State)]
                code = struct.pack("<" + "I" * len(words), *words)
                for value in values:
                    initial_memory = bytes(range(64))
                    buffer = (ctypes.c_uint8 * 64).from_buffer_copy(initial_memory)
                    state = State()
                    state.x[0] = BASE if name == "memory_loop_timeout" else value
                    state.x[1] = 42
                    state.x[30] = 0x20000000
                    state.sp = BASE + 16
                    state.pc = 0x10000000
                    state.nzcv = 0xA0000000
                    state.mem = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8))
                    state.mem_base = BASE
                    state.mem_size = 64
                    expected_ram = bytearray(initial_memory)
                    try:
                        expected = run_reference(
                            code, state, expected_ram, BASE,
                            allow_backward_branches=True, max_steps=BUDGET)
                        timed_out = False
                    except InstructionLimitExceeded:
                        expected = None
                        timed_out = True
                    fn(ctypes.byref(state))
                    self.assertEqual(bytes(buffer), bytes(expected_ram),
                                     (name, value, "RAM"))
                    if timed_out:
                        self.assertEqual(state.fault, 2, (name, value))
                        self.assertEqual(state.pc, 0x10000000, (name, value))
                    else:
                        self.assertEqual(state.fault, 0, (name, value))
                        self.assertEqual(snapshot(state), expected,
                                         (name, value, "CPU"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
