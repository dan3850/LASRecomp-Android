#!/usr/bin/env python3
"""Inspect NSO0 section metadata and scan decompressed text for A64 TLS accesses.

Requires python-lz4 for compressed text (pip install lz4).
Does not execute or modify the game.
"""
import argparse
import hashlib
import struct
from collections import Counter
from pathlib import Path

REGS = {
    0xD53BD040: "MRS_TPIDR_EL0",
    0xD53BD060: "MRS_TPIDRRO_EL0",
    0xD51BD040: "MSR_TPIDR_EL0",
    0xD51BD060: "MSR_TPIDRRO_EL0",
}

def run(path, limit):
    data = path.read_bytes()
    if data[:4] != b"NSO0" or len(data) < 0x70:
        raise ValueError("not a valid-sized NSO0 header")
    flags = struct.unpack_from("<I", data, 0x0c)[0]
    text_off, text_mem, text_size = struct.unpack_from("<III", data, 0x10)
    ro_off, ro_mem, ro_size = struct.unpack_from("<III", data, 0x20)
    data_off, data_mem, data_size = struct.unpack_from("<III", data, 0x30)
    compressed_sizes = struct.unpack_from("<III", data, 0x60)
    print(f"FILE={path}")
    print(f"SHA256={hashlib.sha256(data).hexdigest()}")
    print(f"NSO_FLAGS=0x{flags:08x}")
    for i, (name, offset, mem, size) in enumerate((
        ("text", text_off, text_mem, text_size),
        ("rodata", ro_off, ro_mem, ro_size),
        ("data", data_off, data_mem, data_size),
    )):
        print(f"SECTION_{name} file=0x{offset:x} memory=0x{mem:x} uncompressed=0x{size:x} stored=0x{compressed_sizes[i]:x} compressed={bool(flags & (1 << i))}")
    if not text_size or text_size > 512 * 1024 * 1024:
        raise ValueError("implausible text size")
    compressed = bool(flags & 1)
    stored_size = compressed_sizes[0] if compressed else text_size
    if stored_size <= 0 or text_off + stored_size > len(data):
        raise ValueError("text section extends beyond file")
    text = data[text_off:text_off + stored_size]
    if compressed:
        try:
            import lz4.block
        except ImportError as exc:
            raise RuntimeError("compressed NSO text requires: pip install lz4") from exc
        text = lz4.block.decompress(text, uncompressed_size=text_size)
    if len(text) != text_size:
        raise ValueError("decompressed text size mismatch")
    counts = Counter()
    samples = {name: [] for name in REGS.values()}
    for off in range(0, len(text) - 3, 4):
        word = struct.unpack_from("<I", text, off)[0]
        name = REGS.get(word & ~31)
        if name:
            counts[name] += 1
            if len(samples[name]) < limit:
                samples[name].append((off, word & 31, word))
    print(f"TEXT_DECOMPRESSED_BYTES={len(text)}")
    for name in REGS.values():
        print(f"{name} count={counts[name]}")
        for off, rt, word in samples[name]:
            print(f"  text_offset=0x{off:08x} virtual_address=0x{text_mem + off:08x} reg=x{rt} insn=0x{word:08x}")
    print("NX_NSO_TEXT_AUDIT_OK")

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("main", type=Path)
    p.add_argument("--limit", type=int, default=15)
    a = p.parse_args()
    if not 0 <= a.limit <= 100:
        p.error("--limit must be 0..100")
    run(a.main, a.limit)

if __name__ == "__main__":
    main()
