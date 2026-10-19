"""Conservative AArch64 leaf-to-C recompiler with explicit guest CPU state.

Only supports verified, memoryless instruction forms. Unsupported forms reject
an entire candidate. Generated code is experimental and not a playable port.
"""
import argparse
import struct
from pathlib import Path

from nso import Nso
from analyze import discover

HEADER = """/* Experimental Mario AArch64 leaf recompilation (no game data embedded). */
/* Memory, branches, SIMD and calls remain unsupported. */
#include <stdint.h>

typedef struct MarioA64State {
    uint64_t x[31];  /* x0..x30; register 31 is context-dependent SP or XZR */
    uint64_t sp;
    uint64_t pc;
    uint64_t nzcv;   /* condition flags, preserved by the supported subset */
} MarioA64State;
"""


def translate(words):
    """Return C statements only for an entirely supported function ending in RET X30."""
    if not words:
        return None
    lines = []
    for index, word in enumerate(words):
        if word == 0xD503201F:  # NOP
            continue
        if word == 0xD65F03C0 and index == len(words) - 1:  # RET X30
            lines.append("    s->pc = s->x[30];")
            return lines

        # MOVZ/MOVN/MOVK, immediate, 32- or 64-bit. Destination 31 is WZR/XZR.
        family = word & 0x7F800000
        if family in (0x12800000, 0x52800000, 0x72800000):
            width = 64 if word & 0x80000000 else 32
            hw = (word >> 21) & 3
            if width == 32 and hw > 1:
                return None  # reserved encoding
            dest = word & 31
            value = ((word >> 5) & 0xFFFF) << (16 * hw)
            if dest == 31:
                continue
            if family == 0x52800000:  # MOVZ
                expression = f"0x{value:x}ULL"
            elif family == 0x12800000:  # MOVN
                expression = f"~0x{value:x}ULL"
            else:  # MOVK (insert 16 bits without touching other bits)
                mask = 0xFFFF << (16 * hw)
                expression = f"(s->x[{dest}] & ~0x{mask:x}ULL) | 0x{value:x}ULL"
            if width == 32:
                expression = f"(uint32_t)({expression})"
            lines.append(f"    s->x[{dest}] = {expression};")
            continue

        # ADD/SUB immediate, without flags. Register 31 means SP/WSP.
        family = word & 0x7F000000
        if family in (0x11000000, 0x51000000):
            shift = (word >> 22) & 3
            if shift > 1:
                return None
            width = 64 if word & 0x80000000 else 32
            dest, source = word & 31, (word >> 5) & 31
            src = "s->sp" if source == 31 else f"s->x[{source}]"
            dst = "s->sp" if dest == 31 else f"s->x[{dest}]"
            imm = ((word >> 10) & 0xFFF) << (12 if shift else 0)
            op = "-" if family == 0x51000000 else "+"
            expression = f"{src} {op} 0x{imm:x}ULL"
            if width == 32:
                expression = f"(uint32_t)({expression})"
            lines.append(f"    {dst} = {expression};")
            continue

        return None  # unknown, branches, flags, memory or unsupported RET
    return None  # missing RET


def candidates(nso, limit, min_instructions=2):
    """Conservatively treat the next discovered start as a candidate boundary."""
    funcs, _ = discover(nso)
    starts = sorted(funcs)
    lo, size = nso.text
    hi = lo + size
    count = 0
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else hi
        span = end - start
        if span < min_instructions * 4 or span > 128 or span % 4:
            continue
        words = struct.unpack_from(f"<{span // 4}I", nso.image, start)
        code = translate(words)
        if code is None:
            continue
        yield start, end, code
        count += 1
        if count >= limit:
            break


def render(matches):
    lines = [HEADER]
    for start, end, body in matches:
        lines.append(f"void mario_leaf_{start:08x}(MarioA64State *s) {{")
        lines.extend(body)
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nso", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-instructions", type=int, default=2,
                        help="minimum instructions per candidate (default: 2, excludes bare RET)")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if not 1 <= args.min_instructions <= 32:
        parser.error("--min-instructions must be between 1 and 32")
    nso = Nso(args.nso)
    matches = list(candidates(nso, args.limit, args.min_instructions))
    if not matches:
        raise SystemExit("No functions match the conservative instruction subset; no C emitted")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(matches), encoding="utf-8")
    print(f"Generated {len(matches)} stateful leaf candidates: {args.output}")
    for start, end, _ in matches:
        print(f"  0x{start:x}..0x{end:x}")


if __name__ == "__main__":
    main()
