#!/usr/bin/env python3
"""Read-only coverage census of bounded ARM64 function candidates in a local NSO."""
import argparse
from collections import Counter
import struct
from pathlib import Path

import capstone
from analyze import discover, eh_frame_intervals
from mario_leaf_codegen import translate
from nso import Nso


def analyze(nso, max_bytes=128, examples=5, allow_multiple_ret=False):
    funcs, _ = discover(nso)
    starts = sorted(funcs)
    fde_ranges, fde_stats = eh_frame_intervals(nso)
    fde_counts = Counter()
    text_lo, text_size = nso.text
    text_hi = text_lo + text_size
    counts = Counter()
    counts["discovered"] = len(starts)
    blockers = Counter()
    source_all = Counter(funcs.values())
    source_eligible = Counter()
    source_accepted = Counter()
    prefix_accepted = 0
    samples = {}
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    total_instructions = 0
    accepted_instructions = 0
    rejected_with_early_ret = 0
    rejected_with_zero_word = 0
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else text_hi
        if start in fde_ranges:
            fde_end = fde_ranges[start]
            fde_counts["with_range"] += 1
            fde_counts["shorter" if fde_end < end else "longer" if fde_end > end else "equal"] += 1
            fde_size = fde_end - start
            if 8 <= fde_size <= max_bytes:
                fde_counts["eligible"] += 1
                fde_words = struct.unpack_from("<" + "I" * (fde_size // 4), nso.image, start)
                if translate(fde_words, allow_multiple_ret=allow_multiple_ret) is not None:
                    fde_counts["accepted"] += 1
        size = end - start
        if not (text_lo <= start < end <= text_hi) or size % 4:
            counts["invalid_boundary"] += 1
            continue
        if size < 8:
            counts["too_short"] += 1
            continue
        if size > max_bytes:
            counts["too_long"] += 1
            continue
        counts["eligible"] += 1
        source_eligible[funcs[start]] += 1
        words = struct.unpack_from("<" + "I" * (size // 4), nso.image, start)
        total_instructions += len(words)
        if 0xD65F03C0 in words[:-1]:
            first = words.index(0xD65F03C0)
            if first >= 1 and translate(words[:first + 1]) is not None:
                prefix_accepted += 1
        if translate(words, allow_multiple_ret=allow_multiple_ret) is not None:
            counts["accepted"] += 1
            source_accepted[funcs[start]] += 1
            accepted_instructions += len(words)
            continue
        counts["rejected"] += 1
        if 0xD65F03C0 in words[:-1]:
            rejected_with_early_ret += 1
        if 0 in words:
            rejected_with_zero_word += 1
        # Diagnostic histogram, not an assertion that every occurrence blocks translation.
        # Report instruction forms absent from the supported subset by probing each word
        # with a synthetic final RET. Branches need their original context to validate.
        seen = set()
        for j, word in enumerate(words):
            if word == 0xD65F03C0:
                continue
            if word == 0:
                continue
            if word == 0xD503201F:
                continue
            if (word & 0x7E000000) == 0x34000000:
                continue
            if (word & 0xFF000010) == 0x54000000:
                continue
            if translate((word, 0xD65F03C0)) is not None:
                continue
            code = struct.pack("<I", word)
            decoded = list(md.disasm(code, start + j * 4))
            mnemonic = decoded[0].mnemonic if decoded else "invalid"
            if mnemonic in seen:
                continue
            seen.add(mnemonic)
            blockers[mnemonic] += 1
            if len(samples.get(mnemonic, [])) < examples:
                samples.setdefault(mnemonic, []).append((start + j * 4, word))
    counts["early_ret"] = rejected_with_early_ret
    counts["fde_stats"] = fde_stats
    counts["fde_counts"] = fde_counts
    counts["source_all"] = source_all
    counts["source_eligible"] = source_eligible
    counts["source_accepted"] = source_accepted
    counts["prefix_accepted"] = prefix_accepted
    counts["zero_word"] = rejected_with_zero_word
    return counts, blockers, samples, total_instructions, accepted_instructions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nso", type=Path)
    parser.add_argument("--max-bytes", type=int, default=128)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--examples", type=int, default=3)
    parser.add_argument("--multi-ret", action="store_true",
                        help="diagnostic count for opt-in multiple-RET candidates")
    args = parser.parse_args()
    if args.max_bytes < 8 or args.max_bytes % 4 or args.top < 1 or args.examples < 0:
        parser.error("invalid max-bytes, top or examples")
    nso = Nso(args.nso)
    counts, blockers, samples, total, accepted = analyze(
        nso, args.max_bytes, args.examples, allow_multiple_ret=args.multi_ret)
    print(f"Build ID: {nso.build_id}")
    print(f"Early RET support: {'opt-in enabled' if args.multi_ret else 'disabled (legacy)'}")
    print(f"Discovered starts: {counts['discovered']}")
    print(f"Candidate span: 8..{args.max_bytes} bytes (next discovered start as boundary)")
    print(f"Eligible: {counts['eligible']}; accepted: {counts['accepted']}; rejected: {counts['rejected']}")
    print(f"Excluded: short={counts['too_short']} long={counts['too_long']} invalid={counts['invalid_boundary']}")
    print(f"Eligible instructions: {total}; accepted instructions: {accepted}")
    print("FDE valid={} skipped={}".format(counts["fde_stats"]["valid"], counts["fde_stats"]["skipped"]))
    print("FDE boundaries shorter={} equal={} longer={}".format(counts["fde_counts"]["shorter"], counts["fde_counts"]["equal"], counts["fde_counts"]["longer"]))
    print("FDE candidates eligible={} accepted={} (diagnostic only)".format(counts["fde_counts"]["eligible"], counts["fde_counts"]["accepted"]))
    print("Discovery source: all / eligible / accepted")
    for source in ("eh", "sym", "ptr", "bl"):
        print(f"  {source}: {counts['source_all'][source]} / {counts['source_eligible'][source]} / {counts['source_accepted'][source]}")
    print(f"Translatable first-RET prefixes: {counts['prefix_accepted']} (diagnostic only, not verified function boundaries)")
    print(f"Rejected candidates with early RET: {counts['early_ret']}; containing zero word: {counts['zero_word']}")
    print("Rejected candidates containing each unsupported mnemonic (not unique blockers):")
    for mnemonic, count in blockers.most_common(args.top):
        addresses = ", ".join(f"0x{addr:x}(0x{word:08x})" for addr, word in samples.get(mnemonic, ()))
        print(f"  {mnemonic:12s} {count:7d}  {addresses}")


if __name__ == "__main__":
    main()
