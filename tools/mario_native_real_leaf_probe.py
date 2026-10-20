#!/usr/bin/env python3
"""Run a tightly verified, two-instruction leaf from a local Mario NSO.

EXPERIMENTAL: executes ORIGINAL AArch64 instructions from the locally extracted
game, not generated test bytes. Only exact MOVZ W0/X0,#imm ; RET functions are
eligible. No game initialization, loader relocation, external branches or SVC.
The NSO is never modified, and code is not saved or uploaded.
"""
import argparse
import ctypes
import mmap
from pathlib import Path
import struct
import sys

from nso import Nso

RET = 0xD65F03C0
MOVZ_W0 = 0x52800000
MOVZ_X0 = 0xD2800000
MASK = 0xFFE0001F


def find_leaf(module):
    start, size = module.text
    stop = start + size
    for pc in range(start, stop - 8 + 1, 4):
        word = module.u32(pc)
        if word & MASK not in (MOVZ_W0, MOVZ_X0):
            continue
        if module.u32(pc + 4) != RET:
            continue
        # MOVZ with shift == 0 only; otherwise the result is shifted.
        if (word >> 21) & 3:
            continue
        expected = (word >> 5) & 0xFFFF
        return pc, expected, bytes(module.image[pc:pc + 8])
    return None


def execute_exact_leaf(instructions, expected):
    if sys.platform != "linux" or "aarch64" not in __import__("platform").machine().lower():
        raise RuntimeError("requires native Android/Termux AArch64")
    page_size = mmap.PAGESIZE
    region = mmap.mmap(-1, page_size, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                       prot=mmap.PROT_READ | mmap.PROT_WRITE)
    try:
        region[:8] = instructions
        address = ctypes.addressof(ctypes.c_char.from_buffer(region))
        libc = ctypes.CDLL(None, use_errno=True)
        mprotect = libc.mprotect
        mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
        mprotect.restype = ctypes.c_int
        if mprotect(address, page_size, mmap.PROT_READ | mmap.PROT_EXEC) != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, "mprotect(RX) refused the executable page")
        fn = ctypes.CFUNCTYPE(ctypes.c_uint64)(address)
        result = fn()
        if result != expected:
            raise RuntimeError(f"native return mismatch: {result} != {expected}")
        return result
    finally:
        region.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    for name in ("main", "sdk"):
        nso = Nso(root / name)
        result = find_leaf(nso)
        if result is None:
            print(f"{name}: no safe exact MOVZ+RET candidate")
            continue
        pc, expected, code = result
        if len(code) != 8 or struct.unpack_from("<I", code, 4)[0] != RET:
            raise RuntimeError("candidate changed while reading")
        value = execute_exact_leaf(code, expected)
        print(f"PASS: executed ORIGINAL {name} ARM64 instructions at NSO offset {pc:#x}; return={value}")
        print(f"build_id={nso.build_id}")
        print("SCOPE: isolated exact 2-instruction leaf only; NOT a runnable NSO or game boot.")
        return
    raise SystemExit("NOT_FOUND: neither module contained a permitted simple leaf; no code executed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, AssertionError, ImportError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}")
