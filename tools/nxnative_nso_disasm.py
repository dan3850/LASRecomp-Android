#!/usr/bin/env python3
"""Disassemble selected virtual-address ranges of a compressed Nintendo Switch NSO0.

Reads only the executable text section. Prints an explicit MOD0 signature
check and validates every requested address against the decompressed text.
Requires: python3 -m pip install lz4 capstone
"""
import argparse
import struct
from pathlib import Path

def read_text(path):
    with path.open("rb") as f:
        header = f.read(0x100)
        if len(header) != 0x100 or header[:4] != b"NSO0":
            raise ValueError("expected NSO0 header")
        flags = struct.unpack_from("<I", header, 0x0c)[0]
        file_off, vaddr, unpacked = struct.unpack_from("<III", header, 0x10)
        stored = struct.unpack_from("<I", header, 0x60)[0] if flags & 1 else unpacked
        if not unpacked or unpacked > 512 * 1024 * 1024 or not stored:
            raise ValueError("invalid text section sizes")
        f.seek(0, 2)
        total = f.tell()
        if file_off + stored > total:
            raise ValueError("truncated text section")
        f.seek(file_off)
        packed = f.read(stored)
    if flags & 1:
        import lz4.block
        data = lz4.block.decompress(packed, uncompressed_size=unpacked)
    else:
        data = packed
    if len(data) != unpacked:
        raise ValueError("text section size mismatch")
    return data, vaddr

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nso", type=Path)
    parser.add_argument("--address", action="append", type=lambda s: int(s, 0),
                        help="virtual address, repeatable; default 0x30 and 0x9c22c0")
    parser.add_argument("--count", type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.count <= 200:
        parser.error("--count must be 1..200")
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    except ImportError:
        parser.error("missing Capstone: python3 -m pip install capstone")
    code, base = read_text(args.nso)
    print(f"NSO_TEXT_BASE=0x{base:x} LENGTH=0x{len(code):x}")
    # The first bytes of this particular game appear to contain a MOD0 header;
    # print actual bytes rather than assuming a universal NSO entry convention.
    mod0_positions = [i for i in range(0, min(len(code), 0x100), 4)
                      if code[i:i + 4] == b"MOD0"]
    print("MOD0_SIGNATURE_OFFSETS=" + (",".join(hex(base + i) for i in mod0_positions) or "none"))
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for addr in args.address or [0x30, 0x9c22c0]:
        if addr % 4 or addr < base or addr >= base + len(code):
            print(f"INVALID_ADDRESS=0x{addr:x}")
            continue
        off = addr - base
        segment = code[off:off + args.count * 4]
        print(f"\nDISASM_START=0x{addr:08x}")
        for ins in decoder.disasm(segment, addr):
            print(f"0x{ins.address:08x}: {ins.bytes.hex():8}  {ins.mnemonic:8} {ins.op_str}")
    print("\nNX_NSO_DISASM_OK")

if __name__ == "__main__":
    main()
