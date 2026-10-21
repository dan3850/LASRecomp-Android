#!/usr/bin/env python3
"""Find Mario switch-like case-entry gaps after repeated local B instructions.

Read only the original NSO and the current generated dispatch table. A cluster
of forward unconditional B instructions sharing one local join is evidence for
switch-like cases: the instruction after each B is an unreachable sequential
position and may be reached by a computed BR. It is NOT proof of runtime reach.
The repair tool itself verifies the original game SHA, Build ID and build cache
before changing compiled code.
"""
import argparse
import bisect
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from mario_boot_gap_audit import sha256_file
from mario_resume_repair import parse_table
from nso import Nso

ADDRESS = re.compile(r"^(main|sdk):0x([0-9a-fA-F]+)$")


def b_imm_target(pc, word):
    """Decode only AArch64 B immediate (never BL, B.cond or BR)."""
    if (word & 0xFC000000) != 0x14000000:
        return None
    imm = word & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    return pc + 4 * imm


def clustered_cases(branches, *, lo, hi, spread=0x800, minimum=4):
    """Return candidate case entry -> (join, sources) from bounded clusters."""
    by_join = defaultdict(list)
    for source, join in branches:
        if lo <= source < hi and source + 4 < hi and source < join < hi:
            if join - source <= 0x4000:
                by_join[join].append(source)
    result = {}
    for join, source_sites in sorted(by_join.items()):
        sites = sorted(set(source_sites))
        groups = []
        segment = []
        for site in sites:
            if segment and site - segment[-1] > spread:
                groups.append(segment)
                segment = []
            segment.append(site)
        if segment:
            groups.append(segment)
        for group in groups:
            if len(group) < minimum or group[-1] - group[0] > spread:
                continue
            for site in group:
                candidate = site + 4
                result.setdefault(candidate, (join, tuple(group)))
    return result


def collect_branches(nso, base):
    low, size = nso.text
    for offset in range(low, low + size, 4):
        target = b_imm_target(base + offset, nso.u32(offset))
        if target is not None:
            yield base + offset, target


def select_case_owners(cases, rows, lo, hi, *, observed=None,
                       limit=12, budget_bytes=131072, max_block_bytes=16384,
                       radius=0x4000):
    """Choose whole primary owners; prioritize observed case and nearby cases."""
    if not (1 <= limit <= 32 and 128 <= budget_bytes <= 1048576
            and 16 <= max_block_bytes <= 262144 and 0 <= radius <= 0x100000):
        raise ValueError("invalid bounded case-owner budget")
    primary = sorted(pc for pc, name in rows.items() if name == f"f_{pc:x}")
    if not primary:
        raise ValueError("no primary Mario functions in the generated table")
    if observed is not None and observed not in cases:
        raise ValueError(
            f"observed target {observed:#x} is not a validated B+4 case "
            "in a repeated same-join cluster; no speculative repair")
    pending = {}
    for candidate, evidence in cases.items():
        if candidate in rows or not lo <= candidate < hi:
            continue
        i = bisect.bisect_right(primary, candidate) - 1
        if i < 0:
            continue
        begin = primary[i]
        end = primary[i + 1] if i + 1 < len(primary) else hi
        size = end - begin
        if size < 8 or size > max_block_bytes:
            if candidate == observed:
                raise ValueError(f"observed block exceeds safe size {size}")
            continue
        item = pending.setdefault(begin, {
            "owner": begin, "end": end, "size": size,
            "cases": [], "joins": set(),
        })
        item["cases"].append(candidate)
        item["joins"].add(evidence[0])
    if observed is not None and not any(
            b["owner"] <= observed < b["end"] for b in pending.values()):
        raise ValueError("observed gap is not eligible for reentry")
    center = observed if observed is not None else lo
    candidates = sorted(pending.values(), key=lambda x: (
        not (x["owner"] <= center < x["end"]),
        min(abs(pc - center) for pc in x["cases"]),
        -len(x["cases"]), x["size"], x["owner"]))
    chosen, used = [], 0
    for block in candidates:
        if observed is not None and not (block["owner"] <= observed < block["end"]):
            if min(abs(pc - observed) for pc in block["cases"]) > radius:
                continue
        if len(chosen) >= limit:
            break
        if used + block["size"] > budget_bytes:
            if observed is not None and block["owner"] <= observed < block["end"]:
                raise ValueError("observed case block exceeds byte budget")
            continue
        chosen.append(block)
        used += block["size"]
    if observed is not None and not any(
            b["owner"] <= observed < b["end"] for b in chosen):
        raise ValueError("observed case block not selected")
    return chosen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--target", required=True,
                    help="observed main:0xOFFSET or sdk:0xOFFSET")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--budget-bytes", type=int, default=131072)
    ap.add_argument("--max-block-bytes", type=int, default=16384)
    ap.add_argument("--radius", type=lambda x: int(x, 0), default=0x4000)
    args = ap.parse_args()
    match = ADDRESS.fullmatch(args.target)
    if not match:
        ap.error("target must be main:0xOFFSET or sdk:0xOFFSET")
    name, offset = match.group(1), int(match.group(2), 16)
    if offset & 3:
        ap.error("unaligned target")
    out = args.output.resolve()
    if (out / "resume-transaction").exists():
        ap.error("incomplete resume transaction; preserve build")
    report = json.loads((out / "build-report.json").read_text())
    if report.get("profile") != "mario":
        ap.error("not a Mario build")
    path = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    nso_file = path / name
    info = report["inputs"][name]
    if sha256_file(nso_file) != info["sha256"]:
        ap.error("original NSO SHA256 differs from build: STOP")
    nso = Nso(nso_file)
    if nso.build_id != info["build_id"]:
        ap.error("original NSO Build ID differs from build: STOP")
    base = int(report["bases"][name], 0)
    low, size = nso.text
    lo, hi = base + low, base + low + size
    watched = base + offset
    table = out / "generated" / name / f"{name}_table.c"
    rows = parse_table(table.read_text(), name)
    cases = clustered_cases(collect_branches(nso, base), lo=lo, hi=hi)
    print(f"[mario-case-cluster] module={name} candidates={len(cases)} "
          f"observed={watched:#x}", file=sys.stderr)
    if watched in rows:
        print(f"[mario-case-cluster] observed target already registered",
              file=sys.stderr)
        return
    if watched in cases:
        join, sources = cases[watched]
        print(f"[mario-case-cluster] observed_source={watched - 4:#x} "
              f"join={join:#x} common_join_branches={len(sources)}",
              file=sys.stderr)
    chosen = select_case_owners(
        cases, rows, lo, hi, observed=watched, limit=args.limit,
        budget_bytes=args.budget_bytes,
        max_block_bytes=args.max_block_bytes, radius=args.radius)
    for item in chosen:
        print(f"[mario-case-cluster] repair_owner={item['owner']:#x}.."
              f"{item['end']:#x} bytes={item['size']} "
              f"case_candidates={len(item['cases'])}",
              file=sys.stderr)
    print(" ".join(f"{name}:0x{(watched if item['owner'] <= watched < item['end'] else min(item['cases'])) - base:x}"
                   for item in chosen))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, AssertionError) as error:
        raise SystemExit("ERRO (mario-case-cluster): " + str(error))
