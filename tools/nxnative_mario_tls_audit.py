#!/usr/bin/env python3
"""Audit actual Switch ExeFS/main ARM64 instructions, without modifying ROM.

Counts and samples direct TLS system-register accesses, with file offsets.
Works on raw NSO, decompressed NSO, or extracted main; compressed sections
will not be disassembled. A match is an encoding candidate, not a proven
reachable instruction (data can match too).
"""
import argparse
import hashlib
import mmap
import struct
from collections import Counter
from pathlib import Path

REGS = {
    0xD53BD040: "MRS_TPIDR_EL0",
    0xD53BD060: "MRS_TPIDRRO_EL0",
    0xD51BD040: "MSR_TPIDR_EL0",
    0xD51BD060: "MSR_TPIDRRO_EL0",
}

def audit(path, limit):
    counts = Counter()
    samples = {name: [] for name in REGS.values()}
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
        f.seek(0)
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            print(f"FILE={path}")
            print(f"BYTES={len(data)}")
            print(f"SHA256={digest.hexdigest()}")
            print(f"MAGIC={bytes(data[:4]).hex()} ({'NSO0' if data[:4] == b'NSO0' else 'not NSO0'})")
            for offset in range(0, len(data) - 3, 4):
                word = struct.unpack_from("<I", data, offset)[0]
                name = REGS.get(word & ~31)
                if name is None:
                    continue
                counts[name] += 1
                if len(samples[name]) < limit:
                    samples[name].append((offset, word & 31, word))
    for name in REGS.values():
        print(f"{name} count={counts[name]}")
        for offset, rt, word in samples[name]:
            print(f"  file_offset=0x{offset:08x} reg=x{rt} insn=0x{word:08x}")
    print("NX_MAIN_TLS_AUDIT_OK")
    print("NOTE: offsets are file offsets, not runtime addresses. Compressed NSO sections need decompression.")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path, help="Path to your own extracted Switch ExeFS/main")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if args.limit < 0 or args.limit > 100:
        parser.error("--limit must be between 0 and 100")
    if not args.main.is_file() or args.main.stat().st_size < 4:
        parser.error("input file missing or too small")
    audit(args.main, args.limit)

if __name__ == "__main__":
    main()
