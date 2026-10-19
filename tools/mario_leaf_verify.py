"""Validate Mario leaf C against guest ARM64 via Unicorn or a limited Python reference.

Compiles generated C and compares CPU and optional bounded guest memory. Without Unicorn, the separate Python interpreter
validates only the supported instruction subset, not full CPU equivalence.
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
except (ImportError, OSError):
    uc = None
    A = None

from mario_a64_reference import run_reference
from mario_leaf_codegen import Nso, candidates, render

CODE_BASE = 0x10000000
RAM_BASE = 0x30000000
RAM_SIZE = 0x20000
MASK64 = (1 << 64) - 1


class State(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint64 * 31),
        ("sp", ctypes.c_uint64),
        ("pc", ctypes.c_uint64),
        ("nzcv", ctypes.c_uint64),
        ("mem", ctypes.POINTER(ctypes.c_uint8)),
        ("mem_base", ctypes.c_uint64),
        ("mem_size", ctypes.c_uint64),
        ("fault", ctypes.c_uint64),
    ]


def new_state(rng, serial, with_memory=False):
    state = State()
    special = [0, 1, MASK64, 0xFFFFFFFF, 0x80000000, 0x8000000000000000]
    for i in range(31):
        state.x[i] = (
            RAM_BASE + 0x2000 + rng.randrange(0, 0x2000, 8)
            if with_memory else
            (rng.choice(special) if serial % 2 else rng.getrandbits(64))
        )
    state.x[30] = 0x20000000 + serial * 16
    state.sp = (RAM_BASE + 0x2000 + rng.randrange(0, 0x2000, 16)
                if with_memory else
                RAM_BASE + rng.randrange(0, 0x20000, 16))
    state.pc = CODE_BASE
    state.nzcv = rng.randrange(16) << 28
    buf = None
    if with_memory:
        buf = (ctypes.c_uint8 * RAM_SIZE)()
        pattern = bytes(rng.getrandbits(8) for _ in range(256))
        ctypes.memmove(buf, pattern * (RAM_SIZE // 256), RAM_SIZE)
        state.mem = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8))
        state.mem_base = RAM_BASE
        state.mem_size = RAM_SIZE
    return state, buf

def snapshot(state):
    return tuple(state.x), state.sp, state.pc, state.nzcv & 0xF0000000


def run_original(code, initial, original_ram=None, allow_multiple_ret=False):
    if uc is None:
        guest_ram = bytearray(original_ram) if original_ram is not None else None
        try:
            result = run_reference(code, initial, guest_ram, RAM_BASE,
                                   allow_multiple_ret=allow_multiple_ret)
        except MemoryError:
            return None, bytes(guest_ram) if guest_ram is not None else None, True
        return result, bytes(guest_ram) if guest_ram is not None else None, False

    mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
    mu.mem_map(CODE_BASE, 0x1000)
    mu.mem_write(CODE_BASE, code)
    if original_ram is not None:
        mu.mem_map(RAM_BASE, RAM_SIZE)
        mu.mem_write(RAM_BASE, original_ram)
    for i in range(29):
        mu.reg_write(A.UC_ARM64_REG_X0 + i, initial.x[i])
    mu.reg_write(A.UC_ARM64_REG_X29, initial.x[29])
    mu.reg_write(A.UC_ARM64_REG_X30, initial.x[30])
    mu.reg_write(A.UC_ARM64_REG_SP, initial.sp)
    mu.reg_write(A.UC_ARM64_REG_NZCV, initial.nzcv)
    fault = False
    try:
        mu.emu_start(CODE_BASE, initial.x[30], count=len(code) // 4)
    except uc.UcError as exc:
        if exc.errno not in (uc.UC_ERR_READ_UNMAPPED, uc.UC_ERR_WRITE_UNMAPPED,
                             uc.UC_ERR_READ_PROT, uc.UC_ERR_WRITE_PROT):
            raise
        fault = True
    memory_result = (bytes(mu.mem_read(RAM_BASE, RAM_SIZE))
                     if original_ram is not None else None)
    if fault:
        return None, memory_result, True
    regs = [mu.reg_read(A.UC_ARM64_REG_X0 + i) for i in range(29)]
    regs += [mu.reg_read(A.UC_ARM64_REG_X29), mu.reg_read(A.UC_ARM64_REG_X30)]
    result = (tuple(regs), mu.reg_read(A.UC_ARM64_REG_SP),
              mu.reg_read(A.UC_ARM64_REG_PC),
              mu.reg_read(A.UC_ARM64_REG_NZCV) & 0xF0000000)
    return result, memory_result, False

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--cases", type=int, default=12)
    p.add_argument("--seed", type=int, default=20261019)
    p.add_argument("--with-memory", action="store_true",
                   help="validate bounded W/X LDR STR and memory writes")
    p.add_argument("--require-unicorn", action="store_true",
                   help="Fail instead of using the Python reference interpreter")
    p.add_argument("--use-fde", action="store_true",
                   help="validate FDE-bounded candidates (experimental)")
    p.add_argument("--multi-ret", action="store_true",
                   help="opt in to forward-only multiple-RET function validation")
    args = p.parse_args()
    if args.require_unicorn and uc is None:
        p.error("Unicorn Python module unavailable; omit --require-unicorn for reference comparison")
    if not 1 <= args.limit <= 1000 or not 1 <= args.cases <= 100:
        p.error("--limit must be 1..1000 and --cases 1..100")
    clang = shutil.which("clang")
    if clang is None:
        p.error("clang is required for native validation")
    nso = Nso(args.nso)
    matches = list(candidates(nso, args.limit, min_instructions=2,
                              allow_memory=args.with_memory, use_fde=args.use_fde,
                              allow_multiple_ret=args.multi_ret))
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
        passed = faults = 0
        for start, end, _ in matches:
            fn = getattr(dll, f"mario_leaf_{start:08x}")
            fn.argtypes = [ctypes.POINTER(State)]
            fn.restype = None
            code = bytes(nso.image[start:end])
            for serial in range(args.cases):
                state, buf = new_state(rng, serial, args.with_memory)
                before_ram = bytes(buf) if buf is not None else None
                expected, expected_ram, expected_fault = run_original(
                    code, state, before_ram, allow_multiple_ret=args.multi_ret)
                fn(ctypes.byref(state))
                if bool(state.fault) != expected_fault:
                    raise SystemExit(f"FAIL 0x{start:x} case {serial}: fault mismatch")
                if buf is not None and bytes(buf) != expected_ram:
                    raise SystemExit(f"FAIL 0x{start:x} case {serial}: guest memory differs")
                if expected_fault:
                    if state.pc != CODE_BASE:
                        raise SystemExit(f"FAIL 0x{start:x} case {serial}: PC changed on fault")
                    faults += 1
                    continue
                actual = snapshot(state)
                if actual != expected:
                    for index, (want, got) in enumerate(zip(expected[0], actual[0])):
                        if want != got:
                            detail = f"x{index}: expected 0x{want:x}, got 0x{got:x}"
                            break
                    else:
                        detail = next(
                            f"{name}: expected 0x{expected[i]:x}, got 0x{actual[i]:x}"
                            for i, name in enumerate(("sp", "pc", "nzcv"), 1)
                            if expected[i] != actual[i]
                        )
                    raise SystemExit(f"FAIL 0x{start:x} case {serial}: {detail}")
                passed += 1
        if passed == 0:
            raise SystemExit(f"No successful comparisons; only {faults} guest faults")
        print(f"PASS: {len(matches)} Mario leaf candidates, {passed} successful CPU comparisons, {faults} matching guest faults")
        print("Compared x0..x30, SP, PC, NZCV" + (" and memory" if args.with_memory else "") + ".")
        print("Backend: Unicorn executing original ARM64" if uc is not None else
              "Backend: independent Python ARM64 subset interpreter (not Unicorn)")
        print("Still unsupported: indexed RAM operations, SIMD, branches/calls, dynamic linking.")

if __name__ == "__main__":
    main()
