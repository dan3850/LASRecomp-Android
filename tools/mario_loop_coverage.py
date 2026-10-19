#!/usr/bin/env python3
"""Measure opt-in backward-branch FDE acceptance against Multi-RET baseline.

Counts translation-eligible *candidate spans*, not verified CPU correctness,
executed gameplay paths, or percentage of a playable port. No guest code is
modified or stored in the repository.
"""
import argparse
from pathlib import Path
import struct

from analyze import eh_frame_intervals
from mario_leaf_codegen import translate
from nso import Nso


def compare(nso, max_bytes=128, max_steps=1024, examples=10):
    intervals, stats = eh_frame_intervals(nso)
    eligible = old = enhanced = gained = 0
    sample = []
    for start, end in sorted(intervals.items()):
        size = end - start
        if size < 8 or size > max_bytes or size % 4:
            continue
        words = struct.unpack_from(f"<{size // 4}I", nso.image, start)
        eligible += 1
        baseline = translate(words, allow_multiple_ret=True) is not None
        loops = translate(words, allow_multiple_ret=True,
                          allow_backward_branches=True,
                          max_steps=max_steps) is not None
        old += baseline
        enhanced += loops
        if baseline and not loops:
            raise AssertionError(f"Loop mode lost an accepted candidate: 0x{start:x}")
        if loops and not baseline:
            gained += 1
            if len(sample) < examples:
                sample.append((start, size))
    return eligible, old, enhanced, gained, sample, stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path)
    p.add_argument("--max-bytes", type=int, default=128)
    p.add_argument("--max-steps", type=int, default=1024)
    p.add_argument("--examples", type=int, default=10)
    args = p.parse_args()
    if args.max_bytes < 8 or args.max_bytes % 4 or args.examples < 0:
        p.error("--max-bytes must be a multiple of 4 >= 8; --examples >= 0")
    if not 1 <= args.max_steps <= 1000000:
        p.error("--max-steps must be between 1 and 1000000")
    nso = Nso(args.nso)
    eligible, before, after, gained, sample, stats = compare(
        nso, args.max_bytes, args.max_steps, args.examples)
    print(f"Build ID: {nso.build_id}")
    print(f"FDE valid={stats['valid']} skipped={stats['skipped']}")
    print(f"Eligible FDE intervals (8..{args.max_bytes} bytes): {eligible}")
    print(f"Multi-RET baseline accepted: {before} ({100 * before / eligible:.2f}%)")
    print(f"With internal loops accepted: {after} ({100 * after / eligible:.2f}%)")
    print(f"Additional accepted candidates: +{gained}")
    print(f"Instruction watchdog: {args.max_steps} steps per native invocation")
    print("New candidate examples (guest start, bytes):")
    for start, size in sample:
        print(f"  0x{start:x} size={size}")
    print("Diagnostic only; no guest-loop or game execution is implied by acceptance.")


if __name__ == "__main__":
    main()
