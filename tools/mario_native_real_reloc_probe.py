#!/usr/bin/env python3
"""Apply real Mario NSO relocations to private, NON-executable memory only.

Unresolved symbols remain unresolved; never write bogus addresses.
Inputs are read only. No output file or game code is produced.
"""
import argparse
from collections import Counter
from pathlib import Path
import struct

from nso import Nso
from mario_native_relocator_probe import (
    ABS64, GLOB_DAT, JUMP_SLOT, RELATIVE, apply_relocations, RelocationError
)

BASE = {"main": 0x7000000000, "sdk": 0x7002000000}
KINDS = (ABS64, GLOB_DAT, JUMP_SLOT, RELATIVE)


def exports(nso, base):
    result, ambiguous = {}, set()
    for name, info, section, value, size in nso.syms:
        if not name or not section or not 0 <= value < nso.size:
            continue
        address = base + value
        if name in result and result[name] != address:
            ambiguous.add(name)
        else:
            result[name] = address
    for name in ambiguous:
        result.pop(name, None)
    return result, ambiguous


def apply(name, nso, resolver, ambiguous):
    syms = [(symbol, section, value)
            for symbol, info, section, value, size in nso.syms]
    records, unresolved = [], Counter()
    for record in nso.relocs:
        offset, kind, index, addend = record
        if kind not in KINDS:
            raise RelocationError(f"{name}: unsupported type {kind}")
        if kind != RELATIVE:
            if not 0 <= index < len(syms):
                raise RelocationError(f"{name}: invalid symbol index {index}")
            symbol, section, _ = syms[index]
            if not section and (not symbol or symbol in ambiguous or symbol not in resolver):
                unresolved[symbol or "<unnamed>"] += 1
                continue
        records.append(record)

    # The existing relocator validates all planned writes before mutation.
    image = bytearray(nso.image)
    count = apply_relocations(image, BASE[name], records, syms, resolver.get)
    for offset, kind, index, addend in records:
        if kind == RELATIVE:
            expected = BASE[name] + addend
        else:
            symbol, section, value = syms[index]
            expected = (BASE[name] + value if section else resolver[symbol]) + addend
        actual = struct.unpack_from("<Q", image, offset)[0]
        if actual != expected:
            raise RelocationError(f"{name}: mismatch at {offset:#x}")
    assert count + sum(unresolved.values()) == len(nso.relocs)
    print(f"=== {name} ===")
    print(f"build_id={nso.build_id} relocations={len(nso.relocs)}")
    print(f"applied_and_verified={count} unresolved_records={sum(unresolved.values())}")
    if unresolved:
        for symbol, occurrences in sorted(unresolved.items()):
            print(f"  unresolved {symbol}: {occurrences}")
    print("PASS: all selected relocations verified in private non-executable memory")
    return sum(unresolved.values())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    exefs = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    modules = {name: Nso(exefs / name) for name in ("main", "sdk")}
    if BASE["main"] + modules["main"].size > BASE["sdk"]:
        raise RelocationError("overlapping module address ranges")
    symbols = {name: exports(modules[name], BASE[name]) for name in ("main", "sdk")}
    unresolved = (
        apply("main", modules["main"], *symbols["sdk"]) +
        apply("sdk", modules["sdk"], *symbols["main"])
    )
    print("READ ONLY: original files unchanged, no code executed or output saved")
    print(f"NEEDS_RUNTIME: {unresolved} relocations require external symbol handling")
    print("LIMITS: ABI, x18, TLS, SVC, actual loader protection and runtime remain untested")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError, ValueError, ImportError) as e:
        raise SystemExit(f"ERROR: {e}")
