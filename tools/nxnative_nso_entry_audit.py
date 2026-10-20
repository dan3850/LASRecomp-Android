#!/usr/bin/env python3
"""Inspect the real NSO0 ARM64 entrypoint and its immediate instructions.

The NSO text segment begins at virtual address 0 in the usual NSO layout,
but its first instruction is not necessarily the game's user-level main().
This tool does not attempt to execute the game.
"""
import argparse
import struct
from pathlib import Path

def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path)
    p.add_argument("--instructions", type=int, default=80)
    a = p.parse_args()
    if not 1 <= a.instructions <= 512:
        p.error("--instructions must be 1..512")
    with a.nso.open("rb") as f:
        hdr = f.read(0x100)
        if hdr[:4] != b"NSO0":
            p.error("not an NSO0 file")
        flags = u32(hdr, 0xc)
        off, va, size = struct.unpack_from("<III", hdr, 0x10)
        stored = u32(hdr, 0x60) if flags & 1 else size
        if not stored or size > 512 * 1024 * 1024:
            p.error("invalid text size")
        f.seek(off)
        raw = f.read(stored)
        if len(raw) != stored:
            p.error("truncated NSO text")
    if flags & 1:
        try:
            import lz4.block
        except ImportError:
            p.error("install lz4: python3 -m pip install lz4")
        code = lz4.block.decompress(raw, uncompressed_size=size)
    else:
        code = raw
    if len(code) != size:
        p.error("text decompression size mismatch")
    print(f"NSO_TEXT_VA=0x{va:x} SIZE=0x{size:x}")
    # Switch NSO uses a 4-byte branch at the beginning in typical binaries;
    # only report what is present, do not assume it is an entrypoint.
    print("FIRST_TEXT_INSTRUCTIONS")
    for offset in range(0, min(len(code), a.instructions * 4), 4):
        ins = u32(code, offset)
        label = ""
        if (ins & 0xFC000000) in (0x14000000, 0x94000000):
            delta = ins & 0x03FFFFFF
            if delta & 0x02000000:
                delta -= 0x04000000
            dest = va + offset + delta * 4
            label = f"{'BL' if ins & 0x80000000 else 'B'} target=0x{dest:x}"
        elif ins == 0xD65F03C0:
            label = "RET"
        elif (ins & 0xFFFFFC1F) == 0xD61F0000:
            label = "BR"
        elif (ins & 0xFFFFFC1F) == 0xD63F0000:
            label = "BLR"
        print(f"  VA=0x{va + offset:08x} word=0x{ins:08x} {label}")
    # MOD0 pointer commonly lives at file text offset 4 and is relative to VA 4.
    if len(code) >= 8:
        rel = u32(code, 4)
        signed_rel = rel if rel < (1 << 31) else rel - (1 << 32)
        candidate = va + 4 + signed_rel
        print(f"MOD0_POINTER_CANDIDATE=0x{candidate:x} (unverified)")
    print("NX_NSO_ENTRY_AUDIT_OK")

if __name__ == "__main__":
    main()
