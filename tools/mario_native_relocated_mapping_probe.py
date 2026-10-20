#!/usr/bin/env python3
"""Experimental real-address main/sdk NSO mapping and verified leaf execution.

Maps both user-owned NSOs into private Android memory; uses actual mmap bases,
not synthetic Switch virtual addresses. Resolves validated cross-module
exports and MOD0 relocation boundaries. Leaves unknown glslc/nnos imports
unresolved (never substitutes dummy function pointers). Only executes the
previously validated MOVZ+RET leaf. Does NOT boot the game.
"""
import argparse
from collections import Counter
import ctypes
import mmap
from pathlib import Path
import platform
import struct
import sys

from nso import Nso, DT_RELA, DT_RELASZ, DT_JMPREL, DT_PLTRELSZ
from mario_native_mapped_image_probe import TESTED_OFFSET, verify_leaf
from mario_native_relocator_probe import (
    ABS64, GLOB_DAT, JUMP_SLOT, RELATIVE, RelocationError, apply_relocations
)
from mario_native_real_reloc_probe import exports

KINDS = (ABS64, GLOB_DAT, JUMP_SLOT, RELATIVE)
BOUNDARIES = (
    ("__rel_dyn_start", DT_RELA, DT_RELASZ, False),
    ("__rel_dyn_end", DT_RELA, DT_RELASZ, True),
    ("__rel_plt_start", DT_JMPREL, DT_PLTRELSZ, False),
    ("__rel_plt_end", DT_JMPREL, DT_PLTRELSZ, True),
)


def boundaries(nso, base):
    names, ranges = {}, []
    for name, address_tag, size_tag, end in BOUNDARIES:
        if address_tag not in nso.dyn or size_tag not in nso.dyn:
            raise RelocationError("missing MOD0 dynamic relocation table")
        first, size = nso.dyn[address_tag], nso.dyn[size_tag]
        if size <= 0 or size % 24 or first < 0 or first + size > nso.size:
            raise RelocationError(f"invalid relocation table for {name}")
        names[name] = base + first + (size if end else 0)
        if not end:
            ranges.append((first, first + size))
    if max(ranges[0][0], ranges[1][0]) < min(ranges[0][1], ranges[1][1]):
        raise RelocationError("overlapping MOD0 relocation tables")
    if sum((b - a) // 24 for a, b in ranges) != len(nso.relocs):
        raise RelocationError("MOD0 relocation count mismatch")
    return names


def map_rw(nso):
    page = mmap.PAGESIZE
    size = (nso.size + page - 1) // page * page
    region = mmap.mmap(-1, size, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                       prot=mmap.PROT_READ | mmap.PROT_WRITE)
    region[:nso.size] = nso.image
    address = ctypes.addressof(ctypes.c_char.from_buffer(region))
    return region, address


def relocate_module(nso, base, externally_resolved, conflicts):
    # Preserve all unknown imports as unresolved, not made-up addresses.
    symbols = [(name, section, value)
               for name, info, section, value, size in nso.syms]
    selected, unresolved = [], Counter()
    for record in nso.relocs:
        offset, kind, index, addend = record
        if kind not in KINDS:
            raise RelocationError(f"unsupported relocation kind {kind}")
        if kind != RELATIVE:
            if index < 0 or index >= len(symbols):
                raise RelocationError(f"out of range symbol index {index}")
            name, section, _ = symbols[index]
            if not section and (not name or name in conflicts or name not in externally_resolved):
                unresolved[name or "<unnamed>"] += 1
                continue
        selected.append(record)
    image = bytearray(nso.image)
    written = apply_relocations(image, base, selected, symbols, externally_resolved.get)
    for offset, kind, index, addend in selected:
        if kind == RELATIVE:
            expected = base + addend
        else:
            name, section, value = symbols[index]
            expected = (base + value if section else externally_resolved[name]) + addend
        if struct.unpack_from("<Q", image, offset)[0] != expected:
            raise RelocationError(f"relocation verification mismatch at {offset:#x}")
    if written + sum(unresolved.values()) != len(nso.relocs):
        raise RelocationError("relocation accounting mismatch")
    return image, written, unresolved


def protect_executable_text(nso, base):
    page = mmap.PAGESIZE
    text_start, text_size = nso.text
    start = text_start // page * page
    end = (text_start + text_size + page - 1) // page * page
    if end > nso.size or end <= start:
        raise RelocationError("invalid executable text protection span")
    libc = ctypes.CDLL(None, use_errno=True)
    func = libc.mprotect
    func.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    func.restype = ctypes.c_int
    if func(base + start, end - start, mmap.PROT_READ | mmap.PROT_EXEC):
        raise OSError(ctypes.get_errno(), "mprotect text RX failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    if sys.platform not in ("android", "linux") or platform.machine().lower() not in ("aarch64", "arm64"):
        raise RuntimeError("native Android/Termux ARM64 required")
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    modules = {name: Nso(root / name) for name in ("main", "sdk")}
    expected = verify_leaf(modules["main"])
    mappings = {}
    try:
        for name in ("main", "sdk"):
            region, base = map_rw(modules[name])
            mappings[name] = (region, base)
            print(f"{name}: privately mapped {modules[name].size} bytes at {base:#x}", flush=True)

        module_exports = {name: exports(modules[name], mappings[name][1])
                          for name in ("main", "sdk")}
        for name in ("main", "sdk"):
            nso, (region, base) = modules[name], mappings[name]
            other = "sdk" if name == "main" else "main"
            mapping, conflicts = module_exports[other]
            resolved = dict(mapping)
            resolved.update(boundaries(nso, base))
            patched, count, pending = relocate_module(nso, base, resolved, conflicts)
            region[:nso.size] = patched
            print(f"{name}: applied_and_verified={count} unresolved={sum(pending.values())}", flush=True)
            for symbol, n in sorted(pending.items()):
                print(f"  pending {symbol}: {n}", flush=True)

        for name in ("main", "sdk"):
            protect_executable_text(modules[name], mappings[name][1])

        # This precise two-instruction leaf has no dependencies on relocation
        # records, TLS, SVC, thread state, imports or the runtime.
        main_base = mappings["main"][1]
        func = ctypes.CFUNCTYPE(ctypes.c_uint64)(main_base + TESTED_OFFSET)
        actual = func()
        if actual != expected:
            raise RuntimeError(f"native leaf returned {actual}, expected {expected}")
        print(f"PASS: original main ARM64 leaf returned {actual} inside relocated two-module mappings.")
        print("SCOPE: ONLY the isolated verified MOVZ+RET leaf was executed.")
        print("NOT READY: unresolved glslc/nnos APIs, TLS, x18, SVC, and game startup.")
        print("INPUTS UNCHANGED: local NSOs and APK untouched; no executable image saved.")
    finally:
        for region, base in mappings.values():
            region.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, AssertionError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
