#!/usr/bin/env python3
"""Read-only ARM64 ABI triage, without Capstone/native disassembly libraries.

Counts known SVC and TLS/system-register instruction encodings and reports
a deliberately LIMITED set of x18 instruction patterns. This is not a full
ARM64 decoder: x18 reports are lower bounds and never establish ABI safety.
Does not execute or modify game files.
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import struct

from nso import Nso

TLS = {
    0xD53BD040: "MRS_TPIDR_EL0",
    0xD53BD060: "MRS_TPIDRRO_EL0",
    0xD51BD040: "MSR_TPIDR_EL0",
    0xD51BD060: "MSR_TPIDRRO_EL0",
}
SYS = {
    0xD53BE040: "MRS_CNTVCT_EL0",
    0xD53BE020: "MRS_CNTPCT_EL0",
    0xD53BE000: "MRS_CNTFRQ_EL0",
}


def classify(word):
    # SVC immediate has bits [20:5]; compare opcode with immediate masked.
    if word & 0xFFE0001F == 0xD4000001:
        return "SVC", (word >> 5) & 0xFFFF
    register = word & ~31
    if register in TLS:
        return TLS[register], None
    if register in SYS:
        return SYS[register], None
    # Limited, unambiguous x18 operand patterns. Other classes are not decoded.
    if word & 0xFFFFFC1F in (0xD61F0000, 0xD63F0000, 0xD65F0000):
        return ("X18_BRANCH" if (word >> 5) & 31 == 18 else None), None
    if word & 0x9F000000 == 0x90000000 and word & 31 == 18:
        return "X18_ADRP_DEST", None
    # LDR/STR (unsigned immediate): base and transfer register operands.
    if word & 0x3B000000 == 0x39000000:
        if (word >> 5) & 31 == 18 or word & 31 == 18:
            return "X18_LOADSTORE", None
    return None, None


def audit(name, nso):
    lo, size = nso.text
    counts = Counter()
    samples = defaultdict(list)
    svc_immediates = Counter()
    words = memoryview(nso.image)[lo:lo + size]
    for idx, (word,) in enumerate(struct.iter_unpack("<I", words[:len(words) // 4 * 4])):
        kind, immediate = classify(word)
        if kind is None:
            continue
        counts[kind] += 1
        if len(samples[kind]) < 10:
            samples[kind].append(f"0x{lo + idx * 4:x}")
        if kind == "SVC":
            svc_immediates[immediate] += 1

    print(f"=== {name} ===")
    print(f"build_id={nso.build_id} text_bytes={size}")
    print(f"scanned_aligned_words={len(words) // 4}")
    for kind in ("SVC", *TLS.values(), *SYS.values(),
                 "X18_BRANCH", "X18_ADRP_DEST", "X18_LOADSTORE"):
        print(f"{kind}={counts[kind]} samples={','.join(samples[kind])}")
    print("svc_immediates=" + ", ".join(f"{k:#x}:{v}" for k, v in sorted(svc_immediates.items())))
    print("X18_NOTE: partial opcode coverage only; do not interpret zero as no x18 use")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    combined = Counter()
    for name in ("main", "sdk"):
        combined.update(audit(name, Nso(root / name)))
    print("=== TOTAL ===")
    for kind in ("SVC", *TLS.values(), *SYS.values(),
                 "X18_BRANCH", "X18_ADRP_DEST", "X18_LOADSTORE"):
        print(f"{kind}={combined[kind]}")
    print("READ_ONLY: Python-only scanner; no native library, execution or APK changes.")
    print("NEXT: targeted ARM64 instruction rewriting after independent decoder validation.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError, ImportError, struct.error) as error:
        raise SystemExit(f"ERROR: {error}")
