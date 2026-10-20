#!/usr/bin/env python3
"""Verify MOD0 relocation-table boundaries and resolve those imports in memory.

Works on privately extracted main/sdk NSOs. Does not execute NSO instructions,
save patched images, change original files, or invent external API pointers.
"""
import argparse
from pathlib import Path

from nso import Nso, DT_RELA, DT_RELASZ, DT_JMPREL, DT_PLTRELSZ
from mario_native_real_reloc_probe import BASE, exports, apply
from mario_native_relocator_probe import RelocationError


BOUNDARY_TAGS = (
    ("__rel_dyn_start", DT_RELA, DT_RELASZ, False),
    ("__rel_dyn_end", DT_RELA, DT_RELASZ, True),
    ("__rel_plt_start", DT_JMPREL, DT_PLTRELSZ, False),
    ("__rel_plt_end", DT_JMPREL, DT_PLTRELSZ, True),
)


def derive_boundaries(name, nso):
    resolved = {}
    pairs = []
    for symbol, location_tag, size_tag, is_end in BOUNDARY_TAGS:
        if location_tag not in nso.dyn or size_tag not in nso.dyn:
            raise RelocationError(f"{name}: missing MOD0 dynamic tag for {symbol}")
        start, size = nso.dyn[location_tag], nso.dyn[size_tag]
        if start < 0 or size <= 0 or size % 24 or start + size > nso.size:
            raise RelocationError(
                f"{name}: invalid RELA table for {symbol}: start={start:#x}, size={size}"
            )
        offset = start + size if is_end else start
        resolved[symbol] = BASE[name] + offset
        if not is_end:
            pairs.append((start, start + size))
    # The two relocation tables may be adjacent but must not overlap.
    (a, b), (c, d) = pairs
    if max(a, c) < min(b, d):
        raise RelocationError(f"{name}: overlapping RELA/JMPREL tables")
    expected = sum((end - start) // 24 for start, end in pairs)
    if expected != len(nso.relocs):
        raise RelocationError(
            f"{name}: MOD0 table entries={expected} but parsed {len(nso.relocs)}"
        )
    print(f"{name}: MOD0 relocation tables validated ({expected} records)")
    for key in ("__rel_dyn_start", "__rel_dyn_end",
                "__rel_plt_start", "__rel_plt_end"):
        print(f"  {key}={resolved[key]:#x} (derived, not guessed)")
    return resolved


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    exefs = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    modules = {name: Nso(exefs / name) for name in ("main", "sdk")}
    if BASE["main"] + modules["main"].size > BASE["sdk"]:
        raise RelocationError("module bases overlap")
    known_exports = {name: exports(nso, BASE[name])
                     for name, nso in modules.items()}
    bounds = {name: derive_boundaries(name, nso)
              for name, nso in modules.items()}
    remaining = 0
    for name, other in (("main", "sdk"), ("sdk", "main")):
        external, ambiguous = known_exports[other]
        # Boundaries are per-module, not exports of the other module.
        local_imports = dict(external)
        local_imports.update(bounds[name])
        remaining += apply(name, modules[name], local_imports, ambiguous)
    print(f"NEEDS_RUNTIME: {remaining} relocation records still unresolved.")
    print("READ_ONLY: NSOs untouched; relocations applied only to private bytearrays.")
    print("NO EXECUTION: no real game code executed.")
    print("NOTE: glslc/exception services, TLS/x18 and loader memory protections remain unimplemented.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError, ValueError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
