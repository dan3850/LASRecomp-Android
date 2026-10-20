#!/usr/bin/env python3
"""Find exact, straight-line original ARM64 memory-reading leaf functions.

Read-only by default; no execution in this tool. Unlike the broad ADRP
survey, only complete contiguous sequences ending in RET X30 qualify.
The scan intentionally does not claim that a match is a verified function
entry; a real entry boundary must be established before native execution.
"""
import argparse
from collections import Counter
from pathlib import Path
from nso import Nso


def sext(v, n):
    return v - (1 << n) if v & (1 << (n - 1)) else v


def target_segment(nso, address, width):
    for segment in ("rodata", "data"):
        start, size = getattr(nso, segment)
        if start <= address and address + width <= start + size:
            return segment
    return None


def decode_load(word, reg):
    # unsigned immediate LDR W0/X0, [Xreg, #scaled_imm]
    if (word & 0xFFC003FF) not in (0xB9400000, 0xF9400000):
        return None
    if ((word >> 5) & 31) != reg:
        return None
    width = 8 if word & 0x40000000 else 4
    return ((word >> 10) & 0xFFF) * width, width


def decode_add(word, reg):
    # ADD Xreg, Xreg, #imm12 {, LSL #12}; no flag-setting or SP forms.
    if reg == 31 or (word & 0xFF000000) != 0x91000000:
        return None
    if (word & 31) != reg or (word >> 5) & 31 != reg:
        return None
    shift = (word >> 22) & 3
    if shift not in (0, 1):
        return None
    return ((word >> 10) & 0xFFF) << (12 if shift else 0)


def matches(nso):
    lo, size = nso.text
    end = lo + size
    relocated = set()
    for offset, _, _, _ in nso.relocs:
        relocated.update(range(offset, offset + 8))
    for pc in range(lo, end - 8 + 1, 4):
        word = nso.u32(pc)
        # Case 1: LDR W0/X0, label; RET
        if (word & 0xFF00001F) in (0x18000000, 0x58000000) and nso.u32(pc + 4) == 0xD65F03C0:
            width = 8 if word & 0x40000000 else 4
            address = pc + sext((word >> 5) & 0x7FFFF, 19) * 4
            seg = target_segment(nso, address, width)
            if seg and not any(t in relocated for t in range(address, address + width)):
                yield ("LDR_LITERAL_RET", pc, address, width, seg)
        if pc + 12 > end or (word & 0x9F000000) != 0x90000000:
            continue
        reg = word & 31
        if reg == 31:
            continue
        delta = sext(((((word >> 5) & 0x7FFFF) << 2) | ((word >> 29) & 3)), 21) << 12
        page = (pc & ~0xFFF) + delta
        # Case 2: ADRP Xn; LDR W0/X0, [Xn,imm]; RET
        load = decode_load(nso.u32(pc + 4), reg)
        if load and nso.u32(pc + 8) == 0xD65F03C0:
            disp, width = load
            address = page + disp
            seg = target_segment(nso, address, width)
            if seg and not any(t in relocated for t in range(address, address + width)):
                yield ("ADRP_LDR_RET", pc, address, width, seg)
        if pc + 16 > end:
            continue
        # Case 3: ADRP Xn; ADD Xn,Xn,imm; LDR W0/X0,[Xn,imm]; RET
        add = decode_add(nso.u32(pc + 4), reg)
        load = decode_load(nso.u32(pc + 8), reg)
        if add is not None and load and nso.u32(pc + 12) == 0xD65F03C0:
            disp, width = load
            address = page + add + disp
            seg = target_segment(nso, address, width)
            if seg and not any(t in relocated for t in range(address, address + width)):
                yield ("ADRP_ADD_LDR_RET", pc, address, width, seg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    total = 0
    for name in ("main", "sdk"):
        nso = Nso(root / name)
        kinds = Counter()
        samples = []
        for kind, pc, address, width, seg in matches(nso):
            kinds[kind] += 1
            if len(samples) < 12:
                samples.append(f"{kind} pc={pc:#x} read={address:#x} width={width} segment={seg}")
        print(f"=== {name} build_id={nso.build_id} ===")
        print("exact_sequences=" + str(sum(kinds.values())))
        for kind, n in sorted(kinds.items()):
            print(f"  {kind}={n}")
        for example in samples:
            print("  " + example)
        total += sum(kinds.values())
    if not total:
        print("NOT_FOUND: no safe exact leaf pattern; need control-flow/function-boundary analysis.")
    print("READ_ONLY: no game instructions executed, APK and NSOs unchanged.")
    print("WARNING: contiguous instruction patterns alone do not establish function entry boundaries.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
