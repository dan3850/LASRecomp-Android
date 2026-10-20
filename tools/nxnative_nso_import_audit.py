#!/usr/bin/env python3
"""Resolve an NSO0 AArch64 PLT/GOT slot using MOD0, DT_* and RELA relocations.

This is a read-only diagnostic for extracted Nintendo Switch NSO0 modules.
Install lz4 if the NSO sections are compressed.
"""
import argparse
import struct
from pathlib import Path

def u32(b, p): return struct.unpack_from("<I", b, p)[0]
def i32(b, p): return struct.unpack_from("<i", b, p)[0]
def u64(b, p): return struct.unpack_from("<Q", b, p)[0]

def load(path):
    with path.open("rb") as f:
        hdr = f.read(0x100)
        if hdr[:4] != b"NSO0": raise ValueError("not NSO0")
        flags = u32(hdr, 12)
        sections = []
        for i, base in enumerate((0x10, 0x20, 0x30)):
            offset, va, length = struct.unpack_from("<III", hdr, base)
            stored = u32(hdr, 0x60 + 4*i) if flags & (1 << i) else length
            f.seek(offset)
            raw = f.read(stored)
            if len(raw) != stored: raise ValueError("truncated section")
            if flags & (1 << i):
                import lz4.block
                raw = lz4.block.decompress(raw, uncompressed_size=length)
            if len(raw) != length: raise ValueError("section size mismatch")
            sections.append((va, raw))
    return sections

class Memory:
    def __init__(self, sections): self.sections = sections
    def read(self, addr, size):
        for base, data in self.sections:
            if base <= addr and addr + size <= base + len(data):
                return data[addr-base:addr-base+size]
        raise ValueError(f"unmapped virtual address 0x{addr:x} size={size}")
    def u32(self, a): return u32(self.read(a, 4), 0)
    def i32(self, a): return i32(self.read(a, 4), 0)
    def u64(self, a): return u64(self.read(a, 8), 0)
    def cstr(self, a):
        # Limit strings and never assume a contiguous section.
        chars = bytearray()
        for i in range(1024):
            c = self.read(a+i, 1)
            if c == b"\0": return chars.decode("utf-8", "replace")
            chars.extend(c)
        raise ValueError("symbol string exceeds 1024 bytes")

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path)
    p.add_argument("--slot", type=lambda x:int(x,0), default=0x140e798)
    args = p.parse_args()
    m = Memory(load(args.nso))
    # In this NSO the text starts with an 8-byte prefix followed by MOD0.
    text_base = m.sections[0][0]
    mod0 = None
    for off in range(0, min(0x100, len(m.sections[0][1])-4), 4):
        if m.read(text_base+off, 4) == b"MOD0":
            mod0 = text_base+off
            break
    if mod0 is None: raise ValueError("MOD0 not found in first 0x100 text bytes")
    dynamic = mod0 + m.i32(mod0+4)
    print(f"MOD0=0x{mod0:x} DYNAMIC=0x{dynamic:x}")
    tags = {}
    for i in range(4096):
        tag, value = struct.unpack("<qQ", m.read(dynamic+i*16, 16))
        if tag == 0: break
        tags.setdefault(tag, value)
    else: raise ValueError("unterminated dynamic table")
    for tag, name in ((5,"STRTAB"),(6,"SYMTAB"),(11,"SYMENT"),(23,"JMPREL"),(2,"PLTRELSZ"),(20,"PLTREL"),(7,"RELA"),(8,"RELASZ"),(9,"RELAENT")):
        if tag in tags: print(f"DT_{name}=0x{tags[tag]:x}")
    if 5 not in tags or 6 not in tags: raise ValueError("missing dynamic string/symbol tables")
    syment = tags.get(11, 24)
    if syment < 24: raise ValueError("invalid symbol entry size")
    ranges = []
    if 23 in tags and 2 in tags:
        ranges.append(("JMPREL", tags[23], tags[2]))
    if 7 in tags and 8 in tags:
        ranges.append(("RELA", tags[7], tags[8]))
    if not ranges: raise ValueError("no RELA/JMPREL ranges")
    relaent = tags.get(9, 24)
    if relaent < 24: raise ValueError("invalid RELA entry size")
    found = 0
    for label, start, size in ranges:
        if size % relaent: raise ValueError(f"{label} size not divisible by RELAENT")
        if size // relaent > 2000000: raise ValueError("implausible relocation count")
        for index in range(size//relaent):
            addr = start + index*relaent
            offset, info, addend = struct.unpack("<QQq", m.read(addr, 24))
            if offset != args.slot: continue
            symbol_index, kind = info >> 32, info & 0xffffffff
            sym = m.read(tags[6] + symbol_index*syment, 24)
            name_off = u32(sym, 0)
            name = m.cstr(tags[5]+name_off)
            print(f"MATCH table={label} index={index} slot=0x{offset:x} type={kind} symbol_index={symbol_index} symbol={name!r} addend={addend}")
            found += 1
    print(f"MATCHES={found}")
    print("NX_NSO_IMPORT_AUDIT_OK")
    if not found:
        print("No matching relocation: slot may be populated differently or module metadata differs.")

if __name__ == "__main__":
    main()
