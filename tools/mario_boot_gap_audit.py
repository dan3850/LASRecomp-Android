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
from nso import Nso

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
    print("READ-ONLY: no source, cache, generated library, or APK changed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, AssertionError, struct.error) as exc:
        print("AUDIT FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
