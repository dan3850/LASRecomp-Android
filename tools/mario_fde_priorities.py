#!/usr/bin/env python3
"""Rank missing AArch64 instruction families using real FDE function spans.

NOP replacement is *diagnostic only*: a syntax-rescue proxy, not a working
instruction implementation or an estimate of playable-game completion.
Never emit or run the altered guest functions.
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import struct

import capstone

from analyze import eh_frame_intervals
from mario_leaf_codegen import translate
from nso import Nso

NOP = 0xD503201F
RET = 0xD65F03C0


def is_known_control_flow(word):
    """Branch forms already decoded by translate, even if target is invalid."""
    return ((word & 0xFC000000) == 0x14000000 or
            (word & 0xFF000010) == 0x54000000 or
            (word & 0x7E000000) in (0x34000000, 0x36000000))


def inspect_candidate(words, address, decoder):
    """Return unsupported mnemonic families and diagnostic single-family rescues."""
    missing = defaultdict(list)
    samples = {}
    for index, word in enumerate(words):
        if word == NOP or word == RET or is_known_control_flow(word):
            continue
        if translate((word, RET)) is not None:
            continue
        decoded = next(decoder.disasm(struct.pack("<I", word), address + 4 * index), None)
        family = decoded.mnemonic if decoded is not None else "invalid"
        missing[family].append(index)
        samples.setdefault(family, (address + 4 * index, word))
    rescued = []
    for family, indices in missing.items():
        patched = list(words)
        for index in indices:
            patched[index] = NOP
        if translate(patched) is not None:
            rescued.append(family)
    return set(missing), set(rescued), samples


def analyze_fde(nso, max_bytes=128, examples=2):
    ranges, stats = eh_frame_intervals(nso)
    lo, text_size = nso.text
    hi = lo + text_size
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    totals, present, rescue = Counter(), Counter(), Counter()
    samples = defaultdict(list)
    for start, end in sorted(ranges.items()):
        size = end - start
        if not (lo <= start < end <= hi and size % 4 == 0):
            totals["invalid"] += 1
            continue
        if size < 8:
            totals["too_short"] += 1
            continue
        if size > max_bytes:
            totals["too_long"] += 1
            continue
        totals["eligible"] += 1
        words = struct.unpack_from(f"<{size // 4}I", nso.image, start)
        if translate(words) is not None:
            totals["accepted"] += 1
            continue
        totals["rejected"] += 1
        missing, rescued, found_samples = inspect_candidate(words, start, decoder)
        if not missing:
            totals["structural_only"] += 1
        if len(missing) == 1:
            totals["one_unknown_family"] += 1
        for family in missing:
            present[family] += 1
            if len(samples[family]) < examples:
                samples[family].append(found_samples[family])
        for family in rescued:
            rescue[family] += 1
        if not rescued:
            totals["no_single_family_rescue"] += 1
    totals["fde_valid"], totals["fde_skipped"] = stats["valid"], stats["skipped"]
    return totals, present, rescue, samples


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path, help="locally extracted NSO; never uploaded")
    p.add_argument("--max-bytes", type=int, default=128)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--examples", type=int, default=1)
    args = p.parse_args()
    if args.max_bytes < 8 or args.max_bytes % 4 or args.top < 1 or args.examples < 0:
        p.error("invalid max-bytes, top or examples")
    nso = Nso(args.nso)
    totals, present, rescue, samples = analyze_fde(nso, args.max_bytes, args.examples)
    print(f"Build ID: {nso.build_id}")
    print(f"FDE valid={totals['fde_valid']} skipped={totals['fde_skipped']}")
    print(f"FDE size=8..{args.max_bytes} eligible={totals['eligible']} "
          f"accepted={totals['accepted']} rejected={totals['rejected']}")
    print(f"Excluded: short={totals['too_short']} long={totals['too_long']} "
          f"invalid={totals['invalid']}")
    print(f"Rejected without unknown instruction family: {totals['structural_only']}")
    print(f"Rejected with exactly one unknown family: {totals['one_unknown_family']}")
    print(f"Rejected not rescued by any single-family NOP experiment: "
          f"{totals['no_single_family_rescue']}")
    print("Ranking: NOP-only rescue estimate (DIAGNOSTIC, NOT IMPLEMENTED), "
          "then frequency among rejected FDE functions")
    for family in sorted(present, key=lambda m: (-rescue[m], -present[m], m))[:args.top]:
        example = ", ".join(f"0x{addr:x}(0x{word:08x})"
                            for addr, word in samples[family])
        print(f"  {family:12s} rescue={rescue[family]:5d} "
              f"present={present[family]:5d}  {example}")
    print("NOTE: NOP experiments erase guest behavior and can overstate or "
          "understate real progress. Do not execute these replacements.")


if __name__ == "__main__":
    main()
