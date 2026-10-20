#!/usr/bin/env python3
"""Plan bounded, proactive Mario reentry repairs without modifying generated files.

A repair of any interior PC recompiles its entire containing primary function.
Prioritize the observed failure; optionally add nearby owners with indirect
branch instructions. These are candidates, NOT proven runtime destinations.
"""
import argparse
import bisect
import json
from pathlib import Path
import re
import sys


def select_blocks(rows, base, text_end, anchor_offsets, read_word, *,
                  limit=8, budget_bytes=65536, radius=65536,
                  max_block_bytes=16384):
    if not (1 <= limit <= 32 and 16 <= budget_bytes <= 1048576 and
            4 <= max_block_bytes <= 262144 and 0 <= radius <= 1048576):
        raise ValueError("invalid repair planning limits")
    primary = sorted(pc for pc, fn in rows.items() if fn == f"f_{pc:x}")
    if not primary:
        raise ValueError("no primary function entries")
    anchors = [base + offset for offset in anchor_offsets]
    for pc in anchors:
        if pc & 3 or not primary[0] <= pc < text_end:
            raise ValueError(f"anchor outside compiled text: {pc:#x}")
    choices = []
    for i, owner in enumerate(primary):
        end = primary[i + 1] if i + 1 < len(primary) else text_end
        size = end - owner
        if size < 8:
            continue
        distance = min(max(owner - pc, 0, pc - (end - 4)) for pc in anchors)
        forced = any(owner <= pc < end and pc not in rows for pc in anchors)
        if not forced and distance > radius:
            continue
        if size > max_block_bytes:
            if forced:
                raise ValueError(
                    f"observed target inside oversized block {owner:#x} "
                    f"({size} bytes); use an individual repair or raise "
                    "MARIO_BATCH_BLOCK_BYTES explicitly"
                )
            continue
        resume = f"mario_resume_{owner:x}"
        if rows.get(owner + 4) == resume and rows.get(end - 4) == resume:
            continue  # This block has already been fully expanded.
        anchor = next((pc for pc in anchors
                       if owner <= pc < end and pc not in rows), None)
        target = anchor if anchor is not None else owner + 4
        if target in rows:
            continue
        # BR Xn (computed jump) or BLR Xn (computed call). Do not confuse
        # RET Xn with an indirect branch requiring a resume.
        indirect = any(
            (read_word(pc) & 0xFFFFFC1F) in (0xD61F0000, 0xD63F0000)
            for pc in range(owner, end, 4)
        )
        # Only expand unobserved blocks with an actual indirect branch.
        # Proximity alone must not spend compilation time on arbitrary code.
        if not forced and not indirect:
            continue
        choices.append({
            "owner": owner, "end": end, "size": size,
            "offset": target - base, "forced": forced,
            "indirect": indirect, "distance": distance,
        })
    choices.sort(key=lambda b: (
        not b["forced"], not b["indirect"], b["distance"], b["size"],
        b["owner"],
    ))
    picked, used = [], 0
    for block in choices:
        if len(picked) >= limit:
            break
        if used + block["size"] > budget_bytes:
            if block["forced"]:
                raise ValueError("byte budget too small for the observed failure")
            continue
        picked.append(block)
        used += block["size"]
    for pc in anchors:
        if pc not in rows and not any(b["owner"] <= pc < b["end"] for b in picked):
            raise ValueError(f"required failure not selected: {pc:#x}")
    return picked


def parse_anchors(values):
    result = {"main": [], "sdk": []}
    for value in values:
        match = re.fullmatch(r"(main|sdk):0x([0-9a-fA-F]+)", value)
        if not match:
            raise ValueError("anchor must be main:0xOFFSET or sdk:0xOFFSET")
        offset = int(match.group(2), 16)
        if offset % 4:
            raise ValueError(f"unaligned anchor: {value}")
        if offset not in result[match.group(1)]:
            result[match.group(1)].append(offset)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--anchor", action="append", required=True)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--budget-bytes", type=int, default=65536)
    p.add_argument("--radius", type=int, default=65536)
    p.add_argument("--max-block-bytes", type=int, default=16384)
    args = p.parse_args()
    anchors = parse_anchors(args.anchor)
    from gen import Module
    from mario_resume_repair import parse_table
    from nso import Nso

    out = args.output.expanduser().resolve()
    game = args.game.expanduser().resolve()
    exefs = game / "exefs" if (game / "exefs").is_dir() else game
    report = json.loads((out / "build-report.json").read_text())
    selection = []
    active_modules = [name for name in ("main", "sdk") if anchors[name]]
    if args.limit < len(active_modules):
        raise ValueError("block limit must accommodate all anchored modules")
    per_module_limit = args.limit // len(active_modules)
    for name in active_modules:
        table = out / "generated" / name / (name + "_table.c")
        rows = parse_table(table.read_text(), name)
        base = int(report["bases"][name], 0)
        module = Module(
            name, None, base, report["simd"],
            nso=Nso(exefs / name), profile="mario"
        )
        # The existing repair tool validates exact NSO hashes and build
        # metadata before any file is modified.
        remaining_bytes = args.budget_bytes - sum(
            block["size"] for _, block in selection
        )
        if remaining_bytes < 16:
            raise ValueError("byte budget exhausted before all anchored modules")
        blocks = select_blocks(
            rows, base, module.hi, anchors[name], module.word,
            limit=per_module_limit, budget_bytes=remaining_bytes,
            radius=args.radius, max_block_bytes=args.max_block_bytes
        )
        for b in blocks:
            selection.append((name, b))
    if not selection:
        raise ValueError("no pending repair blocks; no APK will be rebuilt")
    for name, b in selection:
        print(
            f"[mario-batch] {name} block={b['owner']:#x}..{b['end']:#x} "
            f"bytes={b['size']} observed={int(b['forced'])} "
            f"indirect={int(b['indirect'])} distance={b['distance']}",
            file=sys.stderr,
        )
    print(" ".join(f"{name}:0x{b['offset']:x}" for name, b in selection))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit("ERRO (mario-batch): " + str(exc))
