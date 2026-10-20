#!/usr/bin/env python3
"""Read-only survey of REAL Mario ARM64 PC-relative data accesses.

Inspects source instructions from user-supplied NSOs, not executable code.
Finds ADRP Xn + LDR Wt/Xt [Xn, #imm] pairs (adjacent or one ADD between)
and LDR-literal operations with data targets in initialized rodata/data.
Reports counts and sample offsets only. It never executes candidates.
"""
import argparse
from collections import Counter
from pathlib import Path
from nso import Nso


def signextend(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def destination_segment(nso, off, width):
    for name in ("rodata", "data"):
        start, length = getattr(nso, name)
        if start <= off and off + width <= start + length:
            return name
    return None


def scan(nso):
    counts, examples = Counter(), {}
    lo, length = nso.text
    stop = lo + length
    for pc in range(lo, stop - 4, 4):
        word = nso.u32(pc)
        # LDR Wt/Xt, #PC-relative signed immediate
        if (word & 0xFF000000) in (0x18000000, 0x58000000):
            width = 8 if word & 0x40000000 else 4
            target = pc + signextend((word >> 5) & 0x7FFFF, 19) * 4
            seg = destination_segment(nso, target, width)
            if seg:
                key = f"LDR_LITERAL_{seg}"
                counts[key] += 1
                if len(examples.setdefault(key, [])) < 4:
                    examples[key].append((pc, target))
        # ADRP Xn, #page_delta; LDR Rt,[Xn,#offset] may not be adjacent.
        if word & 0x9F000000 != 0x90000000:
            continue
        base_reg = word & 31
        page_delta = signextend((((word >> 5) & 0x7FFFF) << 2) | ((word >> 29) & 3), 21) << 12
        page_off = (pc & ~0xFFF) + page_delta
        for distance in (4, 8, 12, 16):
            insn_pc = pc + distance
            if insn_pc >= stop:
                break
            load = nso.u32(insn_pc)
            # LDR unsigned-immediate Wt or Xt only (not LDUR or STR).
            if (load & 0xFFC00000) not in (0xB9400000, 0xF9400000):
                continue
            if (load >> 5) & 31 != base_reg:
                continue
            width = 8 if load & 0x40000000 else 4
            target = page_off + ((load >> 10) & 0xFFF) * width
            seg = destination_segment(nso, target, width)
            if not seg:
                continue
            key = f"ADRP_LDR_distance_{distance}_{seg}"
            counts[key] += 1
            if len(examples.setdefault(key, [])) < 4:
                examples[key].append((pc, target))
    return counts, examples


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    for name in ("main", "sdk"):
        nso = Nso(root / name)
        counts, examples = scan(nso)
        print(f"=== {name} build_id={nso.build_id} ===")
        for key, count in sorted(counts.items()):
            samples = ",".join(f"pc={pc:#x}->data={target:#x}" for pc, target in examples[key])
            print(f"{key}={count} samples=[{samples}]")
        if not counts:
            print("NO_MATCH: no matching instruction pairs in inspected patterns")
    print("READ_ONLY: no ARM64 code executed; NSO and APK unchanged.")
    print("CAUTION: ADRP pairs may cross branches or overwrite registers; a sample is NOT a verified callable function.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError, ValueError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
