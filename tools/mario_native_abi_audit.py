#!/usr/bin/env python3
"""Audit original Mario NSO AArch64 instructions needing Android adaptation.

Read-only. Uses Capstone to distinguish actual x18 operands from raw bit
patterns. Reports SVC immediates, TLS register access, and x18 use; does not
execute code, change source files, or assume that x18 can be clobbered.
Run: python3 tools/mario_native_abi_audit.py /path/to/Super-extraido
Requires: python3 -m pip install capstone (if not already available).
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from nso import Nso


def inspect_module(name, nso, capstone, arm64):
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    lo, size = nso.text
    samples = defaultdict(list)
    counts = Counter()
    svc_imm = Counter()
    sysreg_counts = Counter()
    for ins in md.disasm(bytes(nso.image[lo:lo + size]), lo):
        is_svc = ins.mnemonic == "svc"
        sysreg = any(tag in ins.op_str.lower()
                     for tag in ("tpidr_el0", "tpidrro_el0", "cntvct_el0", "cntpct_el0", "cntfrq_el0"))
        # x18, w18 register operands. Op strings also include memory bases and
        # address operands; match complete register tokens only.
        import re
        uses_x18 = re.search(r"(?<![\w])(?:x18|w18)(?![\w])", ins.op_str.lower()) is not None
        if is_svc:
            counts["SVC"] += 1
            svc_imm[ins.op_str.strip()] += 1
        if sysreg:
            counts["SYSTEM_REGISTER"] += 1
            for tag in ("tpidr_el0", "tpidrro_el0", "cntvct_el0", "cntpct_el0", "cntfrq_el0"):
                if tag in ins.op_str.lower():
                    sysreg_counts[tag] += 1
        if uses_x18:
            counts["X18_OPERAND"] += 1
        categories = []
        if is_svc:
            categories.append("SVC")
        if sysreg:
            categories.append("SYSTEM_REGISTER")
        if uses_x18:
            categories.append("X18_OPERAND")
        for cat in categories:
            if len(samples[cat]) < 12:
                samples[cat].append(f"0x{ins.address:x} {ins.mnemonic} {ins.op_str}")
    print(f"=== {name} ===")
    print(f"build_id={nso.build_id} text_bytes={size}")
    for cat in ("SVC", "SYSTEM_REGISTER", "X18_OPERAND"):
        print(f"{cat}={counts[cat]}")
        for example in samples[cat]:
            print(f"  {example}")
    print("svc_immediates:", " ".join(f"{k}={v}" for k, v in sorted(svc_imm.items())) or "none")
    print("system_registers:", " ".join(f"{k}={v}" for k, v in sorted(sysreg_counts.items())) or "none")
    print("NOTE: operand sightings are not control-flow coverage or proven runtime calls.")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    try:
        import capstone
        from capstone import arm64
    except ImportError as error:
        parser.error("Capstone required: python3 -m pip install capstone")
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    combined = Counter()
    for name in ("main", "sdk"):
        nso = Nso(root / name)
        combined.update(inspect_module(name, nso, capstone, arm64))
    print("=== TOTAL ===")
    for cat in ("SVC", "SYSTEM_REGISTER", "X18_OPERAND"):
        print(f"{cat}={combined[cat]}")
    print("READ_ONLY: no ARM64 executed, no original NSOs or APK modified.")
    print("NEXT: design x18/TLS-safe trampolines and SVC mappings, then verify individual functions.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}")
