"""Compare Mario leaf C against original AArch64 instructions with Unicorn.

Runs a native temporary .so compiled from the conservative generated C, and
Unicorn emulation of the original bytes, across reproducible random CPU states.
No game assets or generated objects are checked into Git.
"""
import argparse
import ctypes
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    import unicorn as uc
    from unicorn import arm64_const as A
except ImportError:
    uc = None
    A = None

from mario_a64_reference import run_reference
from mario_leaf_codegen import Nso, candidates, render

CODE_BASE = 0x10000000
MASK64 = (1 << 64) - 1


class State(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint64 * 31),
        ("sp", ctypes.c_uint64),
        ("pc", ctypes.c_uint64),
        ("nzcv", ctypes.c_uint64),
    ]


def new_state(rng, serial):
    state = State()
    special = [0, 1, MASK64, 0xFFFFFFFF, 0x80000000, 0x8000000000000000]
    for i in range(31):
        state.x[i] = rng.choice(special) if serial % 2 else rng.getrandbits(64)
    state.x[30] = 0x20000000 + serial * 16
    state.sp = (0x30000000 + rng.randrange(0, 0x20000, 16))
    state.pc = CODE_BASE
    state.nzcv = rng.randrange(16) << 28
    return state


def snapshot(state):
    return tuple(state.x), state.sp, state.pc, state.nzcv & 0xF0000000


def run_original(code, initial):
    if uc is None:
        return run_reference(code, initial)
    mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
    mu.mem_map(CODE_BASE, 0x1000)
    mu.mem_write(CODE_BASE, code)
    for i in range(29):
        mu.reg_write(A.UC_ARM64_REG_X0 + i, initial.x[i])
    mu.reg_write(A.UC_ARM64_REG_X29, initial.x[29])
    mu.reg_write(A.UC_ARM64_REG_X30, initial.x[30])
    mu.reg_write(A.UC_ARM64_REG_SP, initial.sp)
    mu.reg_write(A.UC_ARM64_REG_NZCV, initial.nzcv)
    mu.emu_start(CODE_BASE, initial.x[30], count=len(code) // 4)
    x = [mu.reg_read(A.UC_ARM64_REG_X0 + i) for i in range(29)]
    x += [mu.reg_read(A.UC_ARM64_REG_X29), mu.reg_read(A.UC_ARM64_REG_X30)]
    return (tuple(x), mu.reg_read(A.UC_ARM64_REG_SP),
            mu.reg_read(A.UC_ARM64_REG_PC),
            mu.reg_read(A.UC_ARM64_REG_NZCV) & 0xF0000000)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--cases", type=int, default=12)
    p.add_argument("--seed", type=int, default=20261019)
    p.add_argument("--require-unicorn", action="store_true",
                   help="Fail instead of using the Python reference interpreter")
    args = p.parse_args()
    if args.require_unicorn and uc is None:
        p.error("Unicorn Python module unavailable; omit --require-unicorn for reference comparison")
    if not 1 <= args.limit <= 1000 or not 1 <= args.cases <= 100:
        p.error("--limit must be 1..1000 and --cases 1..100")
    clang = shutil.which("clang")
    if clang is None:
        p.error("clang is required for native validation")
    nso = Nso(args.nso)
    matches = list(candidates(nso, args.limit, min_instructions=2))
    if not matches:
        raise SystemExit("No supported leaf candidates found")
    with tempfile.TemporaryDirectory(prefix="mario-leaf-verify-") as dirname:
        root = Path(dirname)
        source, library = root / "mario_leaf.c", root / "mario_leaf.so"
        source.write_text(render(matches), encoding="utf-8")
        subprocess.run([clang, "-std=c11", "-O2", "-shared", "-fPIC",
                        "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                       check=True)
        dll = ctypes.CDLL(str(library))
        rng = random.Random(args.seed)
        passed = 0
        for start, end, _ in matches:
            fn = getattr(dll, f"mario_leaf_{start:08x}")
            fn.argtypes = [ctypes.POINTER(State)]
            fn.restype = None
            code = bytes(nso.image[start:end])
            for serial in range(args.cases):
                state = new_state(rng, serial)
                baseline = snapshot(state)
                expected = run_original(code, state)
                fn(ctypes.byref(state))
                actual = snapshot(state)
                if actual != expected:
                    for index, (want, got) in enumerate(zip(expected[0], actual[0])):
                        if want != got:
                            detail = f"x{index}: expected 0x{want:x}, got 0x{got:x}"
                            break
                    else:
                        names = ("sp", "pc", "nzcv")
                        detail = next(
                            f"{name}: expected 0x{expected[i]:x}, got 0x{actual[i]:x}"
                            for i, name in enumerate(names, 1) if expected[i] != actual[i]
                        )
                    raise SystemExit(f"FAIL 0x{start:x} case {serial}: {detail}; initial PC 0x{baseline[2]:x}")
                passed += 1
        print(f"PASS: {len(matches)} Mario leaf functions, {passed} CPU-state comparisons")
        print("Compared x0..x30, SP, PC and NZCV.")
        if uc is None:
            print("Backend: independent Python ARM64 subset interpreter (limited validation, not Unicorn)")
        else:
            print("Backend: Unicorn executing original ARM64 bytes")
        print("Unimplemented: RAM accesses, SIMD, branches/calls, full dynamic linking.")


if __name__ == "__main__":
    main()
