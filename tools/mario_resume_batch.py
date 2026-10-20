#!/usr/bin/env python3
"""Plan bounded, proactive Mario reentry repairs without modifying generated files.

A repair of any interior PC recompiles its entire containing primary function.
Prioritize the observed failure; optionally add nearby owners with indirect
branch instructions. Optional nearby-owner coverage handles repeated missing
targets from the same callsite; speculative candidates are NOT proven destinations.
"""
import argparse
import bisect
import json
from pathlib import Path
import re
import sys


def classify_return_site(module, return_offset):
    """Classify the instruction preceding a reported guest LR, not the target.

    An LR alone is insufficient to prove a direct or indirect call. Only
    AArch64 BL/BLR are confirmed here; all other cases remain unknown.
    """
    address = module.base + return_offset
    site = address - 4
    if not module.in_text(site):
        raise ValueError(f"return site outside executable text: {address:#x}")
    word = module.word(site)
    if word & 0xFC000000 == 0x94000000:  # BL immediate
        imm = word & 0x03FFFFFF
        if imm & 0x02000000:
            imm -= 0x04000000
        return ("BL", site + imm * 4)
    if word & 0xFFFFFC1F == 0xD63F0000:  # BLR register
        return ("BLR", None)
    return ("UNKNOWN", None)


def select_blocks(rows, base, text_end, anchor_offsets, read_word, *,
                  limit=8, budget_bytes=65536, radius=65536,
                  max_block_bytes=16384, nearby_radius=0, prefer_forward=False):
    if not (1 <= limit <= 32 and 16 <= budget_bytes <= 1048576 and
            4 <= max_block_bytes <= 262144 and 0 <= radius <= 1048576 and
            0 <= nearby_radius <= radius):
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
        # Targets of an indirect call rarely contain a BR/BLR themselves.
        # A tightly bounded local cohort is useful when consecutive misses
        # share the same LR. Disabled by default to avoid speculative rebuilds.
        nearby = bool(nearby_radius and distance <= nearby_radius)
        if not forced and not indirect and not nearby:
            continue
        choices.append({
            "owner": owner, "end": end, "size": size,
            "offset": target - base, "forced": forced,
            "indirect": indirect, "nearby": nearby,
            "forward": owner > max(anchors), "distance": distance,
        })
    choices.sort(key=lambda b: (
        not b["forced"], not b["nearby"],
        not (prefer_forward and b["forward"]), not b["indirect"],
        b["distance"], b["size"],
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
    p.add_argument("--nearby-radius", type=int, default=0)
    p.add_argument("--prefer-forward", choices=("0", "1"), default="0")
    p.add_argument("--allow-empty", action="store_true", help="succeed without output if all candidates were repaired")
    p.add_argument("--return-site", action="append", default=[],
                   help="reported guest LR as main:0xOFFSET or sdk:0xOFFSET")
    args = p.parse_args()
    anchors = parse_anchors(args.anchor)
    return_sites = parse_anchors(args.return_site)
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
        for offset in return_sites[name]:
            kind, target = classify_return_site(module, offset)
            suffix = f" target={target:#x}" if target is not None else ""
            print(f"[mario-callsite] {name}:0x{offset:x} "
                  f"instruction={kind}{suffix}", file=sys.stderr)
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
            radius=args.radius, max_block_bytes=args.max_block_bytes,
            nearby_radius=args.nearby_radius,
            prefer_forward=args.prefer_forward == "1"
        )
        for b in blocks:
            selection.append((name, b))
    for name in ("main", "sdk"):
        if return_sites[name] and name not in active_modules:
            raise ValueError(f"return site for {name} requires an anchor in that module")
    if not selection:
        if args.allow_empty:
            print("[mario-batch] no pending blocks; reusing compiled objects", file=sys.stderr)
            return
        raise ValueError("no pending repair blocks; no APK will be rebuilt")
    for name, b in selection:
        print(
            f"[mario-batch] {name} block={b['owner']:#x}..{b['end']:#x} "
            f"bytes={b['size']} observed={int(b['forced'])} "
            f"indirect={int(b['indirect'])} nearby={int(b['nearby'])} "
            f"forward={int(b['forward'])} distance={b['distance']}",
            file=sys.stderr,
        )
    print(" ".join(f"{name}:0x{b['offset']:x}" for name, b in selection))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit("ERRO (mario-batch): " + str(exc))
