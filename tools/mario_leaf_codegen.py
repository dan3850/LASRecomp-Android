"""Experimental AArch64 -> C translator for *verified simple leaf functions*.

Only translates a deliberately small instruction subset. Unsupported instructions
cause rejection, never silent omission. No proprietary game bytes are committed.
"""
import argparse
import struct
from pathlib import Path

from nso import Nso
from analyze import discover


def translate(words):
    lines = ["    unsigned long long x[32] = {0};", "    x[0] = arg0;", "    x[1] = arg1;"]
    for word in words:
        if word == 0xD503201F:  # NOP
            continue
        if word == 0xD65F03C0:  # RET X30
            lines.append("    return x[0];")
            return lines
        # MOVZ Xd, #imm16, LSL #(16*hw)
        if (word & 0xFF800000) == 0xD2800000:
            rd = word & 31
            imm = (word >> 5) & 0xFFFF
            shift = ((word >> 21) & 3) * 16
            if rd != 31:
                lines.append(f"    x[{rd}] = 0x{imm << shift:x}ULL;")
            continue
        # MOVK Xd, #imm16, LSL #(16*hw)
        if (word & 0xFF800000) == 0xF2800000:
            rd = word & 31
            imm = (word >> 5) & 0xFFFF
            shift = ((word >> 21) & 3) * 16
            mask = (0xFFFF << shift) & 0xFFFFFFFFFFFFFFFF
            if rd != 31:
                lines.append(f"    x[{rd}] = (x[{rd}] & ~0x{mask:x}ULL) | 0x{imm << shift:x}ULL;")
            continue
        # ADD/SUB (immediate), 64-bit, without flags
        if (word & 0x7F000000) in (0x11000000, 0x51000000) and (word & 0x80000000):
            if word & (1 << 29):  # S bit: ADDS/SUBS unsupported
                return None
            rd, rn = word & 31, (word >> 5) & 31
            shift = (word >> 22) & 3
            if shift > 1 or rd == 31 or rn == 31:
                return None  # SP semantics require dedicated handling
            imm = ((word >> 10) & 0xFFF) << (12 if shift else 0)
            op = "-" if word & (1 << 30) else "+"
            lines.append(f"    x[{rd}] = x[{rn}] {op} {imm}ULL;")
            continue
        return None
    return None  # no RET


def candidates(nso, limit):
    funcs, _ = discover(nso)
    starts = sorted(funcs)
    lo, size = nso.text
    hi = lo + size
    count = 0
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else hi
        if end - start < 4 or end - start > 128 or (end - start) % 4:
            continue
        words = struct.unpack_from(f"<{(end-start)//4}I", nso.image, start)
        translated = translate(words)
        if translated is None:
            continue
        yield start, end, translated
        count += 1
        if count >= limit:
            break


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nso", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    if a.limit < 1 or a.limit > 1000:
        p.error("--limit must be between 1 and 1000")
    n = Nso(a.nso)
    matches = list(candidates(n, a.limit))
    if not matches:
        raise SystemExit("No functions match the conservative subset; no C emitted")
    lines = [
        "/* Generated from a locally owned NSO; limited experimental translation. */",
        "/* ABI: only x0/x1 inputs; no stack, calls, SIMD, memory or flags. */",
        "#include <stdint.h>",
        "",
    ]
    for start, end, body in matches:
        lines.append(f"uint64_t mario_leaf_{start:08x}(uint64_t arg0, uint64_t arg1) {{")
        lines.extend(body)
        lines.append("}")
        lines.append("")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {len(matches)} restricted leaf functions: {a.output}")
    for start, end, _ in matches:
        print(f"  0x{start:x}..0x{end:x}")


if __name__ == "__main__":
    main()
