#!/usr/bin/env python3
"""Compare legacy versus opt-in multi-RET FDE coverage without running guest code.

Each count is a *candidate subset*, not game progress. Guest executable
stays on the user's device; no patches or binaries are emitted.
"""
import argparse
from pathlib import Path
import struct

from analyze import eh_frame_intervals
from mario_leaf_codegen import translate
from nso import Nso


def compare(nso, max_bytes=128, examples=10):
    ranges, fde_stats = eh_frame_intervals(nso)
    eligible = legacy = enhanced = gained = 0
    gained_addresses = []
    for start, end in sorted(ranges.items()):
        length = end - start
        if length < 8 or length > max_bytes or length % 4:
            continue
        words = struct.unpack_from(f"<{length // 4}I", nso.image, start)
        eligible += 1
        old_ok = translate(words) is not None
        new_ok = translate(words, allow_multiple_ret=True) is not None
        legacy += old_ok
        enhanced += new_ok
        if old_ok and not new_ok:
            raise AssertionError(f"Unexpected regression at 0x{start:x}")
        if new_ok and not old_ok:
            gained += 1
            if len(gained_addresses) < examples:
                gained_addresses.append((start, length, words.count(0xD65F03C0)))
    return eligible, legacy, enhanced, gained, gained_addresses, fde_stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nso", type=Path)
    parser.add_argument("--max-bytes", type=int, default=128)
    parser.add_argument("--examples", type=int, default=10)
    args = parser.parse_args()
    if args.max_bytes < 8 or args.max_bytes % 4 or args.examples < 0:
        parser.error("max-bytes must be >=8 and multiple of 4; examples >=0")
    nso = Nso(args.nso)
    eligible, old, new, gain, addresses, stats = compare(
        nso, args.max_bytes, args.examples)
    print(f"Build ID: {nso.build_id}")
    print(f"FDE valid={stats['valid']} skipped={stats['skipped']}")
    print(f"Eligible size=8..{args.max_bytes}: {eligible}")
    print(f"Single-RET accepted: {old} ({old / eligible * 100:.2f}%)")
    print(f"Opt-in multi-RET accepted: {new} ({new / eligible * 100:.2f}%)")
    print(f"Additional candidates: +{gain}")
    print("Examples (guest start, size bytes, number of RET X30):")
    for start, length, returns in addresses:
        print(f"  0x{start:x} size={length} ret={returns}")
    print("Experimental forward-only/last-RET restriction remains; no calls or loops.")


if __name__ == "__main__":
    main()
