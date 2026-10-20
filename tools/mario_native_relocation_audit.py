#!/usr/bin/env python3
"""Read-only relocation and symbol-linkage audit for local Mario main/sdk NSOs.

This is a preflight for future ARM64-native loading, NOT a relocator or loader.
No proprietary data or generated game code is written to disk or uploaded.
"""
import argparse
from collections import Counter
from pathlib import Path

from nso import Nso

RELOC = {257: "ABS64", 1025: "GLOB_DAT", 1026: "JUMP_SLOT", 1027: "RELATIVE"}
MODULES = ("main", "sdk")


def audit(name, nso, other_exports):
    issues = Counter()
    counts = Counter()
    examples = {}
    undefined = Counter()
    resolved_from_other = Counter()
    for offset, kind, sym_index, addend in nso.relocs:
        counts[RELOC.get(kind, f"UNKNOWN_{kind}")] += 1
        if offset < 0 or offset + 8 > nso.size or offset & 7:
            issues["invalid_or_unaligned_relocation_destination"] += 1
            examples.setdefault("invalid_or_unaligned_relocation_destination", hex(offset))
        if kind not in RELOC:
            issues["unsupported_relocation_type"] += 1
            examples.setdefault("unsupported_relocation_type", str(kind))
        if kind == 1027:
            if sym_index != 0:
                issues["RELATIVE_nonzero_symbol_index"] += 1
            if not (0 <= addend < nso.size):
                issues["RELATIVE_addend_outside_module_image"] += 1
                examples.setdefault("RELATIVE_addend_outside_module_image", hex(addend))
            continue
        if not 0 <= sym_index < len(nso.syms):
            issues["invalid_symbol_index"] += 1
            examples.setdefault("invalid_symbol_index", str(sym_index))
            continue
        symbol, _, section, value, _ = nso.syms[sym_index]
        if section == 0:
            if not symbol:
                issues["unnamed_undefined_symbol"] += 1
                continue
            undefined[symbol] += 1
            if symbol in other_exports:
                resolved_from_other[symbol] += 1
        elif not 0 <= value < nso.size:
            issues["defined_symbol_value_outside_image"] += 1
            examples.setdefault("defined_symbol_value_outside_image", f"{symbol}: {value:#x}")
    print(f"=== {name} ===")
    print(f"build_id={nso.build_id} relocations={len(nso.relocs)} symbols={len(nso.syms)}")
    print("relocation_types:", " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"undefined_relocation_symbol_names={len(undefined)}")
    print(f"matched_in_other_module={len(resolved_from_other)}")
    missing = sorted(set(undefined) - set(resolved_from_other))
    print(f"not_exported_by_other_module={len(missing)}")
    if missing:
        print("unmatched_symbol_examples:", ", ".join(missing[:12]))
    if issues:
        for key, count in sorted(issues.items()):
            print(f"CHECK {key}={count} example={examples.get(key, '-')}")
    else:
        print("PASS: relocation destinations, kinds and referenced symbol indices pass structural checks")
    print("NOTE: unmatched imports may be handled by runtime/HLE; this audit does not test symbol resolution.")
    return issues


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    exefs = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    loaded = {name: Nso(exefs / name) for name in MODULES}
    exports = {
        name: {symbol for symbol, _, section, _, _ in nso.syms if symbol and section != 0}
        for name, nso in loaded.items()
    }
    problems = 0
    for name in MODULES:
        other = next(n for n in MODULES if n != name)
        problems += sum(audit(name, loaded[name], exports[other]).values())
    print("READ_ONLY: analyzed local NSOs; no code was executed or rewritten.")
    print("LIMITS: actual loader relocations, dependency resolution, TLS/x18 and Horizon services remain untested.")
    if problems:
        print(f"NEEDS_REVIEW: {problems} structural/assumption warnings")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, ImportError) as e:
        raise SystemExit(f"ERROR: {e}")
