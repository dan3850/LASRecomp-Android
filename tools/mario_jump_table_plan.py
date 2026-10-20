#!/usr/bin/env python3
"""Plan a whole observed ARM64 byte-offset branch table without compiling.

For the Mario profile only. A crash may carry the table-base register (e.g.
x22), ADR branch base, index and target. Validate the observed entry against
the user's private NSO before planning all bounded cases. This is not a
general jump-table recognizer and does not alter the generated code.
"""
import argparse
import bisect
import hashlib
import json
import sys
from pathlib import Path

from mario_boot_gap_audit import parse_table
from nso import Nso


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for data in iter(lambda: source.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def plan(nso, base, registered, table_rva, branch_base_rva, count, *,
         observed_index, observed_target_rva, observed_byte=None):
    """Return (complete case targets, missing interior targets) in RVA form."""
    if not 1 <= count <= 64:
        raise ValueError("case count must be 1..64")
    if not 0 <= observed_index < count:
        raise ValueError("observed index is outside bounded table")
    ro, rsize = nso.rodata
    # A table read by LDRB must belong to the read-only input image.
    if not (ro <= table_rva and table_rva + count <= ro + rsize):
        raise ValueError("table pointer or count is outside original rodata")
    text_lo, text_size = nso.text
    raw = bytes(nso.image[table_rva:table_rva + count])
    if observed_byte is not None and raw[observed_index] != observed_byte:
        raise ValueError("observed LDRB byte does not match NSO contents")
    targets = [branch_base_rva + 4 * item for item in raw]
    expected = branch_base_rva + 4 * raw[observed_index]
    if expected != observed_target_rva:
        raise ValueError(f"logged target mismatch: NSO predicts {expected:#x}, "
                         f"log shows {observed_target_rva:#x}")
    for target in targets:
        if (target & 3) or not text_lo <= target < text_lo + text_size:
            raise ValueError(f"table target {target:#x} outside aligned executable text")
    missing = sorted(set(t for t in targets if base + t not in registered))
    return targets, missing, raw


def run(args):
    game = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    build_report = json.loads((args.output / "build-report.json").read_text(encoding="utf-8"))
    if build_report.get("profile") != "mario":
        raise ValueError("not a Mario recompilation report")
    info = build_report["inputs"][args.module]
    game_file = game / args.module
    if sha256_file(game_file) != info["sha256"]:
        raise ValueError("game NSO hash mismatch; no target plan created")
    nso = Nso(game_file)
    if nso.build_id != info["build_id"]:
        raise ValueError("game NSO Build ID mismatch")
    base = int(build_report["bases"][args.module], 0)
    table, _ = parse_table(args.output / "generated" / args.module /
                           (args.module + "_table.c"), args.module)
    targets, missing, raw = plan(
        nso, base, set(table), args.table_rva, args.branch_base_rva,
        args.count, observed_index=args.observed_index,
        observed_target_rva=args.observed_target_rva,
        observed_byte=args.observed_byte)
    print(f"Read-only verified table for {args.module}: {list(raw)}",
          file=sys.stderr)
    print("Cases: " + ", ".join(f"{args.module}+{x:#x}" for x in targets),
          file=sys.stderr)
    print(f"Distinct new entries: {len(missing)} (of {len(set(targets))} unique cases)",
          file=sys.stderr)
    # stdout is intentionally machine-readable and contains no private bytes.
    print(" ".join(f"{args.module}:0x{t:x}" for t in missing))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--module", choices=("main", "sdk"), default="main")
    parser.add_argument("--table-rva", required=True, type=lambda x: int(x, 0))
    parser.add_argument("--branch-base-rva", required=True, type=lambda x: int(x, 0))
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--observed-index", type=int, required=True)
    parser.add_argument("--observed-target-rva", required=True, type=lambda x: int(x, 0))
    parser.add_argument("--observed-byte", type=lambda x: int(x, 0))
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, KeyError, OSError, AssertionError, IndexError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
