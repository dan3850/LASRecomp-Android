#!/usr/bin/env python3
"""Read-only audit of a Mario guest dispatch miss. Never compile or copy game data."""
import argparse
import bisect
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from nso import Nso, R_AARCH64_ABS64, R_AARCH64_GLOB_DAT, R_AARCH64_JUMP_SLOT, R_AARCH64_RELATIVE

ADDRESS = re.compile(r"^(main|sdk):0x([0-9a-fA-F]+)$")


def parse_table(path, name):
    content = path.read_text(encoding="utf-8")
    match = re.search(r"const uint64_t " + name + r"_fn_addrs\[\] = \{(.*?)\};", content, re.S)
    if not match:
        raise ValueError("missing generated dispatcher table: " + str(path))
    entries = [int(s, 16) for s in re.findall(r"0x[0-9a-fA-F]+", match.group(1))]
    if not entries or entries != sorted(set(entries)):
        raise ValueError("dispatcher table has duplicate or unsorted entries")
    starts = sorted(int(x, 16) for x in re.findall(
        r"^void f_([0-9a-f]+)\(Cpu \*c\);$", content, re.M))
    if not starts:
        raise ValueError("missing normal recompiler function declarations")
    return entries, starts


def owner(starts, pc):
    i = bisect.bisect_right(starts, pc) - 1
    return starts[i] if i >= 0 else None


def instruction_kind(word):
    if word & 0xFFFFFC1F == 0xD63F0000:
        return "BLR indirect call"
    if word & 0xFFFFFC1F == 0xD61F0000:
        return "BR indirect jump"
    if word & 0xFFFFFC1F == 0xD65F0000:
        return "RET"
    if word & 0xFC000000 == 0x94000000:
        return "BL direct call"
    if word & 0xFC000000 == 0x14000000:
        return "B direct jump"
    return "other instruction"


def local_code_relocation_targets(nso):
    """Local executable pointer targets from standard AArch64 ELF relocations.

    This is a sound subset, not a complete C++ vtable/indirect-call analysis.
    Absolute imports resolved in another NSO and pointers built at runtime
    cannot be inferred here.
    """
    low, size = nso.text
    high = low + size
    for site, kind, sym, addend in nso.relocs:
        if kind == R_AARCH64_RELATIVE:
            offset = addend
        elif kind in (R_AARCH64_ABS64, R_AARCH64_GLOB_DAT, R_AARCH64_JUMP_SLOT):
            if sym >= len(nso.syms) or not nso.syms[sym][2]:
                continue
            offset = nso.syms[sym][3] + addend
        else:
            continue
        if low <= offset < high and not offset & 3:
            yield offset, site, kind


def relocation_census(name, nso, base, entries, starts, watched_offsets):
    found = {}
    for offset, site, kind in local_code_relocation_targets(nso):
        found.setdefault(offset, []).append((site, kind))
    known = set(entries)
    unknown = sorted(offset for offset in found if base + offset not in known)
    unknown_owners = {
        owner(starts, base + offset) for offset in unknown
    }
    unknown_owners.discard(None)
    print(f"  STATIC CODE POINTERS {name}: {len(found)} distinct local relocation targets; "
          f"{len(unknown)} without an exact dispatcher entry; "
          f"{len(unknown_owners)} containing blocks")
    for offset in watched_offsets:
        matches = found.get(offset)
        if matches:
            sources = ", ".join(
                f"reloc@{site:#x}/type{kind}" for site, kind in matches[:5])
            print(f"  POINTER SOURCE {name}+{offset:#x}: "
                  f"{len(matches)} relocation(s): {sources}")
        else:
            print(f"  POINTER SOURCE {name}+{offset:#x}: "
                  "not present in recognized local relocations (runtime "
                  "construction, cross-module pointer, or other encoding possible)")
    for offset in unknown[:12]:
        print(f"  MISSING STATIC POINTER {name}+{offset:#x}: "
              f"owner={owner(starts, base + offset)}")
    print("  This census does not prove all indirect destinations are covered.")


def direct_bl_target(nso, lr_offset):
    """Direct BL at LR-4, if present, using a signed AArch64 imm26."""
    low, size = nso.text
    site = lr_offset - 4
    if site % 4 or site < low or site + 4 > low + size:
        return None
    instruction = nso.u32(site)
    if instruction & 0xfc000000 != 0x94000000:
        return None
    displacement = instruction & 0x03ffffff
    if displacement & 0x02000000:
        displacement -= 0x04000000
    return site + displacement * 4


def trace_direct_call(name, nso, base, entries, starts, lr_offset, target_offset):
    """Show every instruction near a direct callee and the missing destination.

    A saved LR proves only where the caller will return, not the exact BR
    that later entered the missing destination. Avoid guessing that source.
    """
    callee = direct_bl_target(nso, lr_offset)
    if callee is None:
        print("  DIRECT-CALL TRACE: LR-4 is not a direct BL in the NSO")
        return
    print(f"  DIRECT-CALL TRACE: LR-4 => {name}+{callee:#x}; "
          f"failed PC={name}+{target_offset:#x}")
    known = set(entries)
    if base + callee not in known:
        print("  WARNING: direct BL callee lacks an exact table entry")
    if abs(callee - target_offset) > 0x400:
        print("  Source and target are farther than 0x400 bytes; "
              "no local-path inference")
        return
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
        from capstone.arm64 import ARM64_OP_IMM
    except ImportError:
        print("  Capstone not installed; no disassembly available")
        return
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoder.detail = True
    low, size = nso.text
    begin = max(low, min(callee, target_offset) - 16) & ~3
    end = min(low + size, max(callee, target_offset) + 48)
    prev_owner = None
    missed_by_direct = []
    count = 0
    for addr in range(begin, end, 4):
        if count >= 192:
            print("  Disassembly truncated at 192 instructions")
            break
        decoded = list(decoder.disasm(nso.image[addr:addr + 4], base + addr))
        if not decoded:
            print(f"  {name}+{addr:#x}: invalid AArch64 word")
            continue
        ins = decoded[0]
        this_owner = owner(starts, base + addr)
        if this_owner != prev_owner:
            print(f"  GENERATED OWNER changes at {name}+{addr:#x}: "
                  f"{this_owner:#x}" if this_owner is not None
                  else "  GENERATED OWNER: unknown")
            prev_owner = this_owner
        label = []
        if addr == callee:
            label.append("direct BL entry")
        if addr == target_offset:
            label.append("missing PC")
        if base + addr in known:
            label.append("registered")
        is_direct = ins.mnemonic in ("b", "bl", "cbz", "cbnz", "tbz", "tbnz") or ins.mnemonic.startswith("b.")
        if is_direct and ins.operands and ins.operands[-1].type == ARM64_OP_IMM:
            jump = ins.operands[-1].imm
            if jump == base + target_offset:
                missed_by_direct.append(addr)
                label.append("DIRECT TARGETS MISSING PC")
        if ins.mnemonic in ("br", "blr"):
            label.append("indirect branch/call")
        detail = ("  [" + "; ".join(label) + "]") if label else ""
        print(f"  {name}+{addr:#x}: {ins.mnemonic} {ins.op_str}{detail}")
        count += 1
    if missed_by_direct:
        print("  DIRECT JUMPS to missing PC from: " +
              ", ".join(f"{name}+{r:#x}" for r in missed_by_direct))
        print("  This is a direct-branch boundary discovery problem.")
    else:
        print("  No direct branch to the missing PC in the shown callee window. "
              "An indirect jump is possible, not proven.")



def target_window_bounds(text_start, text_size, target, return_site=None):
    """Bound a read-only AArch64 window around the missing instruction.

    Include LR-4 only when it is near the target. An LR need not be the
    origin of a BR; it is simply annotated for inspection.
    """
    high = text_start + text_size
    if target & 3 or not text_start <= target < high:
        raise ValueError("target outside aligned executable text")
    begin = max(text_start, target - 40 * 4)
    end = min(high, target + 16 * 4)
    if return_site is not None and abs(return_site - target) <= 0x200:
        begin = min(begin, max(text_start, return_site - 20))
        end = max(end, min(high, return_site + 20))
    return begin, end


def trace_target_window(name, nso, base, entries, starts, target, return_site=None):
    """Show original words around the missing PC, without rebuilding game code."""
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    except ImportError:
        print("  TARGET DISASSEMBLY: Capstone unavailable (read-only audit continues)")
        return
    low, size = nso.text
    begin, end = target_window_bounds(low, size, target, return_site)
    cs = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    registered = set(entries)
    print(f"  TARGET DISASSEMBLY {name}+{begin:#x}..{end:#x}:")
    previous_owner = None
    for off in range(begin, end, 4):
        pc = base + off
        block = owner(starts, pc)
        if block != previous_owner:
            print(f"    OWNER {block:#x}" if block is not None else
                  "    OWNER: unknown")
            previous_owner = block
        insns = list(cs.disasm(bytes(nso.image[off:off + 4]), pc))
        ins = insns[0] if insns else None
        instruction = f"{ins.mnemonic} {ins.op_str}" if ins else f".word {nso.u32(off):#010x}"
        marks = []
        if off == target:
            marks.append("MISSING TARGET")
        if return_site is not None and off == return_site - 4:
            marks.append("LR-4 (not necessarily originating branch)")
        if pc in registered:
            marks.append("registered")
        if ins and ins.mnemonic in ("br", "blr"):
            marks.append("INDIRECT")
        annotation = "  <-- " + ", ".join(marks) if marks else ""
        print(f"    {name}+{off:#x}: {instruction}{annotation}")
    print("  NOTE: LR proximity is not proof of a direct call, switch, or valid entry.")

def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def show(name, offset, lr_offset, base, nso, entries, starts):
    pc = base + offset
    low, size = nso.text
    if offset % 4 or not base + low <= pc < base + low + size:
        raise ValueError(f"{name}+{offset:#x} is not in executable aligned text")
    i = bisect.bisect_left(entries, pc)
    exact = i < len(entries) and entries[i] == pc
    candidate = owner(starts, pc)
    last_registered = owner(entries, pc)
    print(f"TARGET {name}+{offset:#x}: "
          + ("REGISTERED EXACTLY" if exact else "NOT REGISTERED"))
    print(f"  original-function candidate: {candidate:#x}"
          if candidate is not None else "  original-function candidate: none")
    print(f"  closest registered address: {last_registered:#x}"
          if last_registered is not None else "  closest registered address: none")
    if candidate is not None:
        print(f"  offset inside candidate: {pc - candidate:#x}")
    if lr_offset is not None:
        lr = base + lr_offset
        if base + low <= lr - 4 < base + low + size:
            w = nso.u32(lr_offset - 4)
            print(f"  LR={lr:#x}, LR-4: {instruction_kind(w)}")
            try:
                from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
            except ImportError:
                print("  optional capstone unavailable; classification above is still valid")
            else:
                decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
                left = max(low, lr_offset - 40) & ~3
                right = min(low + size, lr_offset + 32)
                print("  surrounding AArch64 instructions:")
                for p in range(left, right, 4):
                    asm = list(decoder.disasm(nso.image[p:p + 4], base + p))
                    if asm:
                        x = asm[0]
                        print(f"    {base + p:#x}: {x.mnemonic} {x.op_str}"
                              + ("  <-- LR-4" if p == lr_offset - 4 else ""))
        else:
            print(f"  LR {lr:#x}: outside this module's executable text")
    print("  INTERPRETATION: " + (
        "Address is present in the generated table. Investigate APK/library mismatch."
        if exact else
        "Exact-match dispatcher cannot call this target. Examine indirect branch "
        "source and candidate function boundary before any new repair."))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--return-site")
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--trace-target", action="store_true",
                        help="disassemble original ARM64 around the missing PC and LR (read-only)")
    parser.add_argument("--trace-callee", action="store_true",
                        help="disassemble direct BL callee near failed PC (read-only)")
    parser.add_argument("--scan-relocations", action="store_true",
                        help="count executable pointers missed by the exact dispatcher (read only)")
    args = parser.parse_args()
    if (args.output / "resume-transaction").exists():
        parser.error("incomplete resume transaction: preserve all build files")
    report = json.loads((args.output / "build-report.json").read_text(encoding="utf-8"))
    if report.get("profile") != "mario" or not report.get("inputs") or not report.get("bases"):
        parser.error("valid Mario build report is missing")
    game = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    specs = {}
    for field, label in [("target", args.target),
                         ("return-site", args.return_site),
                         *[("check", x) for x in args.check]]:
        if not label:
            continue
        match = ADDRESS.fullmatch(label)
        if not match:
            parser.error(f"invalid {field}: {label}")
        specs.setdefault(match.group(1), []).append((field, int(match.group(2), 16)))
    for name, values in specs.items():
        path = game / name
        if sha256_file(path) != report["inputs"][name]["sha256"]:
            parser.error(f"{name}: input hash differs from generated library; STOP")
        nso = Nso(path)
        if nso.build_id != report["inputs"][name]["build_id"]:
            parser.error(f"{name}: Build ID differs from generated library; STOP")
        base = int(report["bases"][name], 0)
        entries, starts = parse_table(
            args.output / "generated" / name / f"{name}_table.c", name)
        print(f"MODULE {name}: functions={len(starts)} table_entries={len(entries)} "
              f"build_id={nso.build_id[:16]}")
        return_site = next((v for field, v in values if field == "return-site"), None)
        for field, offset in values:
            if field != "return-site":
                show(name, offset, return_site if field == "target" else None,
                     base, nso, entries, starts)
        if args.trace_target:
            target = next((v for field, v in values if field == "target"), None)
            if target is not None:
                trace_target_window(name, nso, base, entries, starts,
                                    target, return_site)
        if args.trace_callee and return_site is not None:
            target = next((v for field, v in values if field == "target"), None)
            if target is not None:
                trace_direct_call(name, nso, base, entries, starts,
                                  return_site, target)
        if args.scan_relocations:
            relocation_census(name, nso, base, entries, starts,
                              [offset for field, offset in values if field != "return-site"])
    print("READ-ONLY: no source, cache, generated library, or APK changed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, AssertionError, struct.error) as exc:
        print("AUDIT FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
