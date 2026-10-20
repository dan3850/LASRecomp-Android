#!/usr/bin/env python3
"""Execute a VERIFIED original Mario ARM64 leaf inside a full mapped NSO image.

Unlike mario_native_real_leaf_probe.py, this maps the entire private main
image at once. Only the independently verified MOVZ+RET leaf is called.
This is NOT a real NSO loader: no relocations, TLS, imports or SVC are used.
Files are read-only; no game code is stored in the Git repository.
"""
import argparse
import ctypes
import mmap
import platform
from pathlib import Path
import struct
import sys

from nso import Nso

TESTED_BUILD_ID = "891687f016a18f1773d4a88ebf8a973c8e33ecc1"
TESTED_OFFSET = 0x92BA0
MOVZ_X0 = 0xD2800000
MOVZ_W0 = 0x52800000
RET = 0xD65F03C0


def verify_leaf(nso):
    if nso.build_id != TESTED_BUILD_ID:
        raise ValueError(f"main Build ID differs; refusing execution: {nso.build_id}")
    start, length = nso.text
    if not (start <= TESTED_OFFSET and TESTED_OFFSET + 8 <= start + length):
        raise ValueError("tested address outside executable text")
    first, second = struct.unpack_from("<II", nso.image, TESTED_OFFSET)
    if second != RET or first & 0xFFE0001F not in (MOVZ_W0, MOVZ_X0):
        raise ValueError("tested leaf no longer matches MOVZ W0/X0 + RET")
    if (first >> 21) & 3:
        raise ValueError("unexpected MOVZ shift")
    expected = (first >> 5) & 0xFFFF
    if expected != 5:
        raise ValueError(f"unexpected leaf return value {expected}")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    if sys.platform not in ("linux", "android") or platform.machine().lower() not in ("aarch64", "arm64"):
        raise RuntimeError(f"native Android ARM64 required: {sys.platform}/{platform.machine()}")
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    nso = Nso(root / "main")
    expected = verify_leaf(nso)
    page = mmap.PAGESIZE
    length = (nso.size + page - 1) & -page
    region = mmap.mmap(-1, length, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                       prot=mmap.PROT_READ | mmap.PROT_WRITE)
    try:
        region[:nso.size] = nso.image
        address = ctypes.addressof(ctypes.c_char.from_buffer(region))
        lo, size = nso.text
        executable_start = lo & -page
        executable_end = (lo + size + page - 1) & -page
        if executable_end > length:
            raise RuntimeError("executable text exceeds mapped image")
        libc = ctypes.CDLL(None, use_errno=True)
        mprotect = libc.mprotect
        mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
        mprotect.restype = ctypes.c_int
        if mprotect(address + executable_start, executable_end - executable_start,
                    mmap.PROT_READ | mmap.PROT_EXEC):
            errno = ctypes.get_errno()
            raise OSError(errno, "mprotect of NSO executable pages refused")
        entry = ctypes.CFUNCTYPE(ctypes.c_uint64)(address + TESTED_OFFSET)
        observed = entry()
        if observed != expected:
            raise RuntimeError(f"leaf returned {observed}, expected {expected}")
        print(f"PASS: original main NSO mapped in private memory ({nso.size} bytes).")
        print(f"PASS: ARM64 leaf at offset {TESTED_OFFSET:#x} returned {observed} from the mapped image.")
        print("LIMITS: only validated MOVZ+RET executed; no relocations, external calls, TLS or SVC.")
        print("INPUTS UNCHANGED: no original NSO, APK or ROM files were modified.")
    finally:
        region.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, AssertionError, ValueError, ImportError) as e:
        raise SystemExit(f"ERROR: {e}")
