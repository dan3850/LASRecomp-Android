#!/usr/bin/env python3
"""Recognize bounded AArch64 ADRP/ADD/ADR/LDRB/ADD/BR switch tables.

Mario-only, based on the *original* local NSO, not runtime guesses. Every
candidate must have a matching CMP/B.HI bound, read-only byte table, correct
register data flow and in-text destinations. Plan whole owning blocks for the
existing transactional incremental reentry repair. No game code is uploaded.
"""
import argparse
import bisect
import json
import re
import sys
from pathlib import Path

from mario_boot_gap_audit import parse_table, sha256_file
from nso import Nso

REG = r"([0-9]|[12][0-9]|30)"
NUM = r"(?:0x[0-9a-f]+|[0-9]+)"


def fields(ins, mnemonic, regex):
    if ins.mnemonic != mnemonic:
        return None
    m = re.fullmatch(regex, ins.op_str.replace(" ", "").lower())
    return m.groups() if m else None


def _number(value):
    return int(value.lstrip("#"), 0)


def recognize(window, nso, base):
    """Return validated (switch_pc_rva, list_of_target_rvas), or None."""
    if len(window) != 8:
        return None
    c, guard, adrp, add1, adr, load, add2, branch = window
    cmp_args = fields(c, "cmp", rf"w{REG},#({NUM})")
    if not cmp_args or not fields(guard, "b.hi", rf"#({NUM})"):
        return None
    cmp_index, limit_raw = cmp_args
    limit = _number(limit_raw)
    if limit > 63:
        return None
    guard_dest = _number(guard.op_str)
    if guard_dest <= branch.address:
        return None
    regs_adrp = fields(adrp, "adrp", rf"x{REG},#({NUM})")
    if not regs_adrp:
        return None
    table_reg, table_page = regs_adrp
    add_args = fields(add1, "add", rf"x{REG},x{REG},#({NUM})")
    if not add_args or add_args[0] != table_reg or add_args[1] != table_reg:
        return None
    entry_args = fields(adr, "adr", rf"x{REG},#({NUM})")
    if not entry_args:
        return None
    target_reg, target_base = entry_args
    load_args = fields(load, "ldrb", rf"w{REG},\[x{REG},x{REG}\]")
    if not load_args:
        return None
    byte_reg, addr_reg, index_reg = load_args
    if addr_reg != table_reg or index_reg != cmp_index:
        return None
    sum_args = fields(add2, "add", rf"x{REG},x{REG},x{REG},lsl#2")
    if not sum_args or sum_args != (target_reg, target_reg, byte_reg):
        return None
    dest_args = fields(branch, "br", rf"x{REG}")
    if not dest_args or dest_args[0] != target_reg:
        return None

    table_rva = _number(table_page) + _number(add_args[2]) - base
    target_base_rva = _number(target_base) - base
    ro, ro_size = nso.rodata
    count = limit + 1
    if not (ro <= table_rva and table_rva + count <= ro + ro_size):
        return None
    start, size = nso.text
    data = nso.image[table_rva:table_rva + count]
    targets = tuple(sorted({target_base_rva + 4 * x for x in data}))
    if any((t & 3) or not start <= t < start + size for t in targets):
        return None
    return {
        "branch_rva": branch.address - base,
        "table_rva": table_rva,
        "target_base_rva": target_base_rva,
        "targets": targets,
        "cases": count,
    }


def _writes_table_register(ins, reg):
    """Conservatively reject a distant ADRP/ADD if its table base is clobbered."""
    try:
        _, written = ins.regs_access()
        names = {ins.reg_name(r).lower() for r in written}
    except Exception:
        # No instruction register detail: cannot prove the distant base survives.
        return True
    return f"x{reg}" in names or f"w{reg}" in names


def recognize_spaced(window, nso, base):
    """Recognize a guarded byte-switch whose table setup predates the guard.

    The final CMP/B.HI/ADR/LDRB/ADD/BR must remain contiguous. The ADRP/ADD
    pair may appear up to 26 preceding instructions earlier, but the table
    register must survive every intervening instruction. Require Capstone
    register-write metadata; do not extrapolate across unknown writes.
    """
    if not 9 <= len(window) <= 32:
        return None
    c, guard, adr, load, add2, branch = window[-6:]
    for a, b in zip(window[-6:-1], window[-5:]):
        if a.address + 4 != b.address:
            return None
    if not fields(c, "cmp", rf"w{REG},#({NUM})"):
        return None
    if not fields(guard, "b.hi", rf"#({NUM})"):
        return None
    if not fields(branch, "br", rf"x{REG}"):
        return None
    # The two table-address instructions must be contiguous, unmodified,
    # and earlier than the final guarded dispatch sequence.
    for i in range(len(window) - 8, -1, -1):
        adrp, add1 = window[i:i + 2]
        if adrp.address + 4 != add1.address:
            continue
        setup = fields(adrp, "adrp", rf"x{REG},#({NUM})")
        if not setup:
            continue
        result = recognize([c, guard, adrp, add1, adr, load, add2, branch],
                           nso, base)
        if result is None:
            continue
        table_reg = setup[0]
        if any(_writes_table_register(ins, table_reg)
               for ins in window[i + 2:-3]):
            continue
        result["layout"] = "spaced-table-base"
        return result
    return None


def scan_switches(nso, base):
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    except ImportError as e:
        raise ValueError("Capstone missing: pkg install python-capstone") from e
    disasm = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    disasm.detail = True
    start, size = nso.text
    image = nso.image
    for offset in range(start + 28, start + size, 4):
        word = nso.u32(offset)
        if word & 0xfffffc1f != 0xd61f0000:
            continue
        beginning = offset - 28
        window = list(disasm.disasm(bytes(image[beginning:offset + 4]), base + beginning))
        result = recognize(window, nso, base) if len(window) == 8 else None
        if result is None:
            # Most addresses aren't indirect BRs; only those are examined
            # with an extended 32-instruction window.
            beginning = max(start, offset - 31 * 4)
            extended = list(disasm.disasm(
                bytes(image[beginning:offset + 4]), base + beginning))
            result = recognize_spaced(extended, nso, base)
        if result:
            yield result


def blocks_for_targets(targets, rows, base, text_hi):
    """Collapse missing switch cases into whole owning blocks, never fake PCs."""
    primary = sorted(pc for pc, fn in rows.items() if fn == f"f_{pc:x}")
    known = set(rows)
    planned = {}
    for offset in sorted(set(targets)):
        pc = base + offset
        if pc in known:
            continue
        i = bisect.bisect_right(primary, pc) - 1
        if i < 0:
            raise ValueError(f"switch target {offset:#x} before first recompiled entry")
        owner = primary[i]
        end = primary[i + 1] if i + 1 < len(primary) else text_hi
        if not owner <= pc < end:
            raise ValueError(f"invalid owner for switch case {offset:#x}")
        planned.setdefault(owner, {
            "owner": owner, "end": end, "bytes": end - owner,
            "targets": [],
        })["targets"].append(pc)
    return planned


def select_census(tables, planned, base, anchor, max_blocks, byte_budget, max_block_bytes):
    """Prioritize complete anchor table, then additional recognized tables.

    Refuse partial coverage of the observed switch even when another complete
    table could fit. Do not silently skip any oversized block in that switch.
    """
    by_branch = {t["branch_rva"]: t for t in tables}
    anchors = [t for t in tables if anchor in t["targets"]]
    if not anchors:
        raise ValueError(f"observed target {anchor:#x} is not in a verified bounded switch")
    priority = sorted(anchors, key=lambda t: (abs(t["branch_rva"] - anchor), t["branch_rva"]))[0]
    def owners_for(table):
        keys = []
        for owner, info in planned.items():
            if any(base + x in info["targets"] for x in table["targets"]):
                keys.append(owner)
        return sorted(keys)
    anchor_owners = owners_for(priority)
    used = set()
    size = 0
    for owner in anchor_owners:
        block = planned[owner]
        if block["bytes"] > max_block_bytes:
            raise ValueError(f"observed switch requires oversized block "
                             f"{owner:#x} ({block['bytes']} bytes)")
        used.add(owner)
        size += block["bytes"]
    if len(used) > max_blocks or size > byte_budget:
        raise ValueError("observed switch exceeds safe block/byte budget")
    for table in sorted(tables, key=lambda t: (
            t["branch_rva"] != priority["branch_rva"],
            abs(t["branch_rva"] - priority["branch_rva"]))):
        if table is priority:
            continue
        owners = set(owners_for(table)) - used
        if not owners or any(planned[o]["bytes"] > max_block_bytes for o in owners):
            continue
        extra = sum(planned[o]["bytes"] for o in owners)
        if len(used) + len(owners) > max_blocks or size + extra > byte_budget:
            continue
        used.update(owners)
        size += extra
    return [planned[owner] for owner in sorted(used)], priority



def select_global_census(tables, planned, base, max_blocks, byte_budget, max_block_bytes):
    """Select only complete, statically verified tables within a strict budget.

    Individual tables are atomic: never claim coverage while leaving an
    unregistered target of that table behind. Owners already registered
    need no repair. Favor tables with fewer missing bytes first.
    """
    if not (1 <= max_blocks <= 64 and 128 <= byte_budget <= 1048576
            and 16 <= max_block_bytes <= 262144):
        raise ValueError("invalid global census limits")
    selected = set()
    used = 0
    candidates = []
    for table in tables:
        owners = {
            owner for owner, block in planned.items()
            if any(base + target in block["targets"] for target in table["targets"])
        }
        candidates.append((sum(planned[o]["bytes"] for o in owners),
                           table["branch_rva"], owners))
    for _, _, owners in sorted(candidates, key=lambda x: (x[0], x[1])):
        new = owners - selected
        if not new or any(planned[o]["bytes"] > max_block_bytes for o in new):
            continue
        extra = sum(planned[o]["bytes"] for o in new)
        if len(selected) + len(new) > max_blocks or used + extra > byte_budget:
            continue
        selected.update(new)
        used += extra
    return [planned[owner] for owner in sorted(selected)]


def valid_selection_mode(all_verified, anchor):
    """Exactly one mode: global verified-table scan or explicit target."""
    return bool(all_verified) != (anchor is not None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--module", choices=("main", "sdk"), default="main")
    ap.add_argument("--anchor", type=lambda x: int(x, 0))
    ap.add_argument("--allow-empty", action="store_true",
                    help="success with no output when a verified table is fully registered")
    ap.add_argument("--all-verified", action="store_true",
                    help="select whole verified jump tables without a crash address")
    ap.add_argument("--max-blocks", type=int, default=16)
    ap.add_argument("--budget-bytes", type=int, default=131072)
    ap.add_argument("--max-block-bytes", type=int, default=16384)
    args = ap.parse_args()
    if not (1 <= args.max_blocks <= 64 and 128 <= args.budget_bytes <= 1048576
            and 16 <= args.max_block_bytes <= 262144
            and (args.anchor is None or (args.anchor >= 0 and args.anchor % 4 == 0))
            and valid_selection_mode(args.all_verified, args.anchor)):
        ap.error("invalid planning bounds")
    output = args.output.resolve()
    if (output / "resume-transaction").exists():
        ap.error("incomplete transaction: preserve build and recover before planning")
    report = json.loads((output / "build-report.json").read_text())
    if report.get("profile") != "mario":
        ap.error("not a Mario build report")
    game = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    game_file = game / args.module
    info = report["inputs"][args.module]
    if sha256_file(game_file) != info["sha256"]:
        ap.error("original game NSO hash mismatch; preserve old generated data")
    nso = Nso(game_file)
    if nso.build_id != info["build_id"]:
        ap.error("original game Build ID mismatch")
    base = int(report["bases"][args.module], 0)
    entries, _ = parse_table(output / "generated" / args.module /
                             (args.module + "_table.c"), args.module)
    # Existing normal entry + interior reentry function both count as registered.
    from mario_resume_repair import parse_table as parse_rows
    rows = parse_rows((output / "generated" / args.module /
                       (args.module + "_table.c")).read_text(), args.module)
    tables = list(scan_switches(nso, base))
    all_targets = [t for table in tables for t in table["targets"]]
    blocks = blocks_for_targets(all_targets, rows, base,
                                base + nso.text[0] + nso.text[1])
    if args.all_verified:
        chosen = select_global_census(tables, blocks, base, args.max_blocks,
                                      args.budget_bytes, args.max_block_bytes)
        observed = None
    else:
        chosen, observed = select_census(tables, blocks, base, args.anchor,
                                         args.max_blocks, args.budget_bytes,
                                         args.max_block_bytes)
    print(f"[mario-static-switch] verified_tables={len(tables)} "
          f"missing_case_targets={len(set(base + x for x in all_targets) - set(entries))} "
          f"pending_owners={len(blocks)}", file=sys.stderr)
    if observed is not None:
        print(f"[mario-static-switch] observed_br={args.module}+0x{observed['branch_rva']:x} "
              f"cases={observed['cases']} table_rva=0x{observed['table_rva']:x} "
              f"observed_target=0x{args.anchor:x}", file=sys.stderr)
    else:
        print(f"[mario-static-switch] verified-global selected_owners={len(chosen)}",
              file=sys.stderr)
    for block in chosen:
        print(f"[mario-static-switch] patch_owner=0x{block['owner']:x} "
              f"bytes={block['bytes']} targets={len(block['targets'])}",
              file=sys.stderr)
    if not chosen:
        if args.all_verified or args.allow_empty:
            print("[mario-static-switch] no pending verified owners", file=sys.stderr)
            return
        raise ValueError("recognized switch has no missing entries: no rebuild needed")
    # Repair one anchor in each owner: transactional repair exposes *all*
    # instruction addresses inside that owner's function, not just the anchor.
    print(" ".join(f"{args.module}:0x{min(b['targets']) - base:x}"
                   for b in chosen))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, ImportError) as error:
        raise SystemExit("ERRO (mario-static-switch): " + str(error))
