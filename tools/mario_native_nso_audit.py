#!/usr/bin/env python3
"""Read-only native-ARM64 compatibility audit for personally extracted Mario NSOs.

Does not execute, patch, copy or export Switch instructions. Only reports
counts/offsets for SVC, TPIDR register access and relocation kinds.
"""
import argparse
from collections import Counter
from pathlib import Path
import sys

from nso import Nso

# MRS/MSR for TPIDR_EL0 and TPIDRRO_EL0, destination/source Rt masked.
# These are only a deliberately narrow instruction-class audit, not a loader.
TLS_REGISTER_ENCODINGS = {
    0xD53BD040: "MRS_TPIDR_EL0",
    0xD53BD060: "MRS_TPIDRRO_EL0",
    0xD51BD040: "MSR_TPIDR_EL0",
    0xD51BD060: "MSR_TPIDRRO_EL0",
}
KNOWN_RELOCS = {257: "ABS64", 1025: "GLOB_DAT", 1026: "JUMP_SLOT", 1027: "RELATIVE"}


def scan(nso):
    start, size = nso.text
    counts = Counter()
    offsets = {}
    for off in range(start, start + size - size % 4, 4):
        w = nso.u32(off)
        kind = None
        if w & 0xFFE0001F == 0xD4000001:
            kind = "SVC"
        else:
            kind = TLS_REGISTER_ENCODINGS.get(w & ~0x1F)
        if kind:
            counts[kind] += 1
            offsets.setdefault(kind, [])
            if len(offsets[kind]) < 8:
                offsets[kind].append(off)
    return counts, offsets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path, help="Extracted directory containing exefs/main and exefs/sdk")
    args = parser.parse_args()
    exefs = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    for name in ("main", "sdk"):
        path = exefs / name
        if not path.is_file():
            parser.error(f"missing local NSO: {path}")
        nso = Nso(path)
        counts, offsets = scan(nso)
        print(f"=== {name} ===")
        print(f"build_id={nso.build_id} text_bytes={nso.text[1]} image_bytes={nso.size}")
        for kind in ("SVC", *TLS_REGISTER_ENCODINGS.values()):
            print(f"{kind}: {counts[kind]} samples=" + ",".join(hex(v) for v in offsets.get(kind, [])))
        reloc = Counter(KNOWN_RELOCS.get(typ, f"UNKNOWN_{typ}") for _, typ, _, _ in nso.relocs)
        print("relocations: " + (", ".join(f"{k}={v}" for k, v in sorted(reloc.items())) or "none"))
        print(f"imports={len(nso.imports())} exports={len(nso.exports())}")
    print("READ_ONLY: no executable bytes exported, no NSO code executed.")
    print("LIMITS: x18 use, all system registers, thread state, runtime and relocations not validated.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, ValueError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
