"""Mario NSO recompilation readiness report; reads the user's local NSO only.

No game binaries, keys, or proprietary assets are written to the repository.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from nso import Nso
from analyze import discover


def report(path):
    nso = Nso(path)
    functions, _ = discover(nso)
    lo, length = nso.text
    hi = lo + length
    ordered = sorted(functions)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    types = Counter(kind for _, kind, _, _ in nso.relocs)
    out_of_image = sum(not 0 <= offset < nso.size for offset, _, _, _ in nso.relocs)
    return {
        "build_id": nso.build_id,
        "image_bytes": nso.size,
        "segments": {
            "text": {"start": lo, "size": length},
            "rodata": {"start": nso.rodata[0], "size": nso.rodata[1]},
            "data": {"start": nso.data[0], "size": nso.data[1]},
            "bss_bytes": nso.bss_size,
        },
        "dependencies": nso.needed,
        "symbols": {"total": len(nso.syms), "imports": len(nso.imports()), "exports": len(nso.exports())},
        "relocations": {"by_type": dict(sorted(types.items())), "offsets_outside_image": out_of_image},
        "function_candidates": {
            "total": len(functions),
            "by_source": dict(Counter(functions.values())),
            "first_20_addresses": [f"0x{x:x}" for x in ordered[:20]],
            "last_20_addresses": [f"0x{x:x}" for x in ordered[-20:]],
            "largest_start_address_gap": max(gaps, default=0),
            "starts_outside_text": sum(not lo <= a < hi for a in ordered),
        },
        "status": "analysis_only_not_recompiled",
        "limitations": [
            "Function starts are candidates; function ends and control flow need validation.",
            "Relocations and external symbols need runtime resolution.",
            "No ARM64-to-C translation, linking or Android game boot is performed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nso", type=Path, help="Local extracted NSO main")
    parser.add_argument("--output", type=Path, help="Optional JSON output file")
    args = parser.parse_args()
    result = report(args.nso)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Report written: {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
