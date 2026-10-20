#!/usr/bin/env python3
"""Identify exact unresolved imports in Mario's real NSOs.

No guessed addresses or stub functions. Read-only: code is not executed,
relocated output not written, and proprietary bytes are not exported.
"""
import argparse
from collections import defaultdict
from pathlib import Path

from nso import Nso

BASES = {"main": 0x7000000000, "sdk": 0x7002000000}
NAMES = ("main", "sdk")
SECTION_TAGS = {
    "__rel_dyn_start", "__rel_dyn_end",
    "__rel_plt_start", "__rel_plt_end",
}


def exports(nso, base):
    values, ambiguous = {}, set()
    for symbol, info, section, off, size in nso.syms:
        if not symbol or not section or not 0 <= off < nso.size:
            continue
        new = base + off
        if symbol in values and values[symbol] != new:
            ambiguous.add(symbol)
        else:
            values[symbol] = new
    for symbol in ambiguous:
        values.pop(symbol, None)
    return values, ambiguous


def unresolved_info(name, nso, cross_exports, ambiguous):
    pending = defaultdict(list)
    for off, kind, idx, addend in nso.relocs:
        if kind == 1027:
            continue
        if not 0 <= idx < len(nso.syms):
            raise ValueError(f"{name}: invalid relocation symbol index {idx}")
        symbol, info, section, value, size = nso.syms[idx]
        if not section and (symbol not in cross_exports or symbol in ambiguous):
            pending[symbol or "<unnamed>"].append((off, kind, idx, addend))
    print(f"=== {name} ===")
    print(f"build_id={nso.build_id} unresolved_names={len(pending)} unresolved_records={sum(map(len, pending.values()))}")
    for symbol, sites in sorted(pending.items()):
        category = ("linker_boundary_candidate" if symbol in SECTION_TAGS
                    else "shader_compiler_api" if symbol.startswith("glslc")
                    else "platform_service_candidate")
        print(f"{symbol}: class={category} count={len(sites)}")
        for off, kind, idx, addend in sites[:4]:
            print(f"  offset=0x{off:x} kind={kind} sym_index={idx} addend={addend}")
    print("NOTE: categories are hints, NOT confirmed addresses or implementations.")
    return pending


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    exefs = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    modules = {name: Nso(exefs / name) for name in NAMES}
    exported = {name: exports(modules[name], BASES[name]) for name in NAMES}
    total = 0
    for name in NAMES:
        other = "sdk" if name == "main" else "main"
        entries = unresolved_info(name, modules[name], *exported[other])
        total += sum(map(len, entries.values()))
    print(f"UNRESOLVED_TOTAL={total}")
    print("NEXT: resolve true linker boundaries and platform APIs in the loader/runtime; never insert dummy pointers.")
    print("READ_ONLY: original NSO files unchanged; no executable memory or game code run.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
