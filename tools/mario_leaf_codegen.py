"""Conservative AArch64 leaf-to-C recompiler with explicit guest CPU state.

Supports restricted bounded memory operations. Unsupported forms reject the
entire candidate. Generated code is experimental and not a playable port.
"""
import argparse
import struct
from pathlib import Path

from nso import Nso
from analyze import discover, eh_frame_intervals

HEADER = """/* Experimental Mario ARM64 leaf translation; no game data embedded. */
#include <stdint.h>
#include <stddef.h>

typedef struct MarioA64State {
    uint64_t x[31];
    uint64_t sp;
    uint64_t pc;
    uint64_t nzcv;
    uint8_t *mem;
    uint64_t mem_base;
    uint64_t mem_size;
    uint64_t fault;
} MarioA64State;

/* Contiguous guest-memory test sandbox. The runtime will need real mappings. */
static inline __attribute__((unused)) int mario_offset(
        const MarioA64State *s, uint64_t addr, size_t width, size_t *off) {
    if (!s->mem || s->mem_size > SIZE_MAX || width > s->mem_size ||
        addr < s->mem_base) return 0;
    uint64_t delta = addr - s->mem_base;
    if (delta > s->mem_size - width) return 0;
    *off = (size_t)delta;
    return 1;
}
static inline __attribute__((unused)) int mario_read(
        MarioA64State *s, uint64_t addr, size_t width, uint64_t *result) {
    size_t off;
    if (!mario_offset(s, addr, width, &off)) return 0;
    uint64_t value = 0;
    for (size_t i = 0; i < width; ++i)
        value |= (uint64_t)s->mem[off + i] << (8 * i);
    *result = value;
    return 1;
}
static inline __attribute__((unused)) int mario_write(
        MarioA64State *s, uint64_t addr, size_t width, uint64_t value) {
    size_t off;
    if (!mario_offset(s, addr, width, &off)) return 0;
    for (size_t i = 0; i < width; ++i)
        s->mem[off + i] = (uint8_t)(value >> (8 * i));
    return 1;
}
"""


def translate(words):
    """Return C statements only for an entirely supported function ending in RET X30."""
    if not words:
        return None
    lines = ["    s->fault = 0;"]
    targets = set()
    for index, word in enumerate(words):
        if (word & 0xFF000010) == 0x54000000:
            if (word & 15) >= 14:
                return None
            imm = (word >> 5) & 0x7FFFF
            displacement = imm - 0x80000 if imm & 0x40000 else imm
            target = index + displacement
            if target <= index or target >= len(words):
                return None
            targets.add(target)
        if (word & 0x7E000000) == 0x34000000:
            imm = (word >> 5) & 0x7FFFF
            displacement = imm - 0x80000 if imm & 0x40000 else imm
            target = index + displacement
            if target <= index or target >= len(words):
                return None  # forward-only, inside this function
            targets.add(target)
        if (word & 0x7E000000) == 0x36000000:
            imm = (word >> 5) & 0x3FFF
            displacement = imm - 0x4000 if imm & 0x2000 else imm
            target = index + displacement
            if target <= index or target >= len(words):
                return None
            targets.add(target)
        if (word & 0xFC000000) == 0x14000000:
            imm = word & 0x03FFFFFF
            displacement = imm - 0x04000000 if imm & 0x02000000 else imm
            target = index + displacement
            if target <= index or target >= len(words):
                return None  # forward-only; never jump outside the candidate
            targets.add(target)
    for index, word in enumerate(words):
        if index in targets:
            lines.append(f"mario_label_{index}: ;")
        if (word & 0xFC000000) == 0x14000000:
            imm = word & 0x03FFFFFF
            displacement = imm - 0x04000000 if imm & 0x02000000 else imm
            target = index + displacement
            lines.append(f"    goto mario_label_{target};")
            continue
        if (word & 0xFC000000) == 0x14000000:
            imm = word & 0x03FFFFFF
            displacement = imm - 0x04000000 if imm & 0x02000000 else imm
            target = index + displacement
            lines.append(f"    goto mario_label_{target};")
            continue
        if (word & 0x7E000000) == 0x36000000:
            imm = (word >> 5) & 0x3FFF
            displacement = imm - 0x4000 if imm & 0x2000 else imm
            target = index + displacement
            rt = word & 31
            bit = ((word >> 31) << 5) | ((word >> 19) & 31)
            value = "0ULL" if rt == 31 else f"s->x[{rt}]"
            op = "!=" if word & 0x01000000 else "=="
            lines.append(f"    if ((({value} >> {bit}) & 1ULL) {op} 0ULL) goto mario_label_{target};")
            continue
        if (word & 0xFF000010) == 0x54000000:
            imm = (word >> 5) & 0x7FFFF
            displacement = imm - 0x80000 if imm & 0x40000 else imm
            target = index + displacement
            cond = word & 15
            if cond >= 14 or target <= index or target >= len(words):
                return None
            predicates = [
                "z", "!z", "c", "!c", "n", "!n", "v", "!v",
                "c && !z", "!c || z", "n == v", "n != v",
                "!z && (n == v)", "z || (n != v)",
            ]
            lines.append("    {")
            lines.append("        uint64_t flags = s->nzcv;")
            flag_names = ("n", "z", "c", "v")
            flag_bits = (31, 30, 29, 28)
            for name, bit in zip(flag_names, flag_bits):
                if name in predicates[cond].replace("&&", " ").replace("||", " ").replace("!", " ").replace("==", " ").replace("!=", " ").split():
                    lines.append(f"        int {name} = (flags >> {bit}) & 1;")
            lines.append(f"        if ({predicates[cond]}) goto mario_label_{target};")
            lines.append("    }")
            continue
        if (word & 0x7E000000) == 0x34000000:
            imm = (word >> 5) & 0x7FFFF
            displacement = imm - 0x80000 if imm & 0x40000 else imm
            target = index + displacement
            if target <= index or target >= len(words):
                return None
            rt = word & 31
            value = "0ULL" if rt == 31 else f"s->x[{rt}]"
            if not (word & 0x80000000):
                value = f"(uint32_t)({value})"
            op = "!=" if word & 0x01000000 else "=="
            lines.append(f"    if ({value} {op} 0ULL) goto mario_label_{target};")
            continue
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

        # MOV register alias of ORR (shifted register), LSL #0, Rn=XZR/WZR.
        # Preserve flags; Rd=31 discards the value and Rm=31 reads zero.
        if (word & 0x7FE0FFE0) == 0x2A0003E0:
            dest, source = word & 31, (word >> 16) & 31
            if dest != 31:
                value = "0ULL" if source == 31 else f"s->x[{source}]"
                if not (word & 0x80000000):
                    value = f"(uint32_t)({value})"
                lines.append(f"    s->x[{dest}] = {value};")
            continue

        # AND/ORR/EOR immediate, AArch64 logical bitmask encoding.
        if (word & 0x1F800000) == 0x12000000:
            sf = bool(word & 0x80000000)
            opc = (word >> 29) & 3
            n = (word >> 22) & 1
            immr = (word >> 16) & 63
            imms = (word >> 10) & 63
            width = 64 if sf else 32
            if not sf and n:
                return None
            packed = (n << 6) | ((~imms) & 63)
            length = packed.bit_length() - 1
            if length < 1:
                return None
            levels = (1 << length) - 1
            s = imms & levels
            r = immr & levels
            if s == levels:
                return None
            element_width = 1 << length
            element = (1 << (s + 1)) - 1
            r %= element_width
            element = ((element >> r) | (element << (element_width - r))) & ((1 << element_width) - 1)
            mask = 0
            for shift in range(0, width, element_width):
                mask |= element << shift
            rd, rn = word & 31, (word >> 5) & 31
            source = "0ULL" if rn == 31 else f"s->x[{rn}]"
            operation = ("&", "|", "^", "&")[opc]
            expression = f"({source} {operation} 0x{mask:x}ULL)"
            if width == 32:
                expression = f"(uint32_t){expression}"
            if opc == 3:
                lines.append(f"    {{ uint64_t result = {expression};")
                lines.append(f"      s->nzcv = ((result >> {width - 1}) << 31) | ((result == 0) << 30); }}")
            elif rd != 31:
                lines.append(f"    s->x[{rd}] = {expression};")
            continue

        # ADDS/SUBS immediate, including CMP alias (SUBS with Rd=31).
        family = word & 0x7F000000
        if family in (0x31000000, 0x71000000):
            shift = (word >> 22) & 3
            if shift > 1:
                return None
            width = 64 if word & 0x80000000 else 32
            mask = "UINT64_MAX" if width == 64 else "UINT32_MAX"
            dest, source = word & 31, (word >> 5) & 31
            src = "s->sp" if source == 31 else f"s->x[{source}]"
            imm = ((word >> 10) & 0xFFF) << (12 if shift else 0)
            subtract = family == 0x71000000
            lines.append("    {")
            lines.append(f"        uint64_t a = {src} & {mask};")
            lines.append(f"        uint64_t b = 0x{imm:x}ULL;")
            lines.append(f"        uint64_t result = (a {'-' if subtract else '+'} b) & {mask};")
            lines.append(f"        uint64_t sign = 1ULL << {width - 1};")
            lines.append("        uint64_t n = (result & sign) != 0;")
            lines.append("        uint64_t z = result == 0;")
            if subtract:
                lines.append("        uint64_t carry = a >= b;")
                lines.append("        uint64_t overflow = ((a ^ b) & (a ^ result) & sign) != 0;")
            else:
                lines.append(f"        uint64_t carry = a > ({mask} - b);")
                lines.append("        uint64_t overflow = (~(a ^ b) & (a ^ result) & sign) != 0;")
            lines.append("        s->nzcv = (n << 31) | (z << 30) | (carry << 29) | (overflow << 28);")
            if dest != 31:
                lines.append(f"        s->x[{dest}] = result;")
            lines.append("    }")
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

        # Unsigned-offset LDR/STR, W/X only. Rn=31 is SP; Rt=31 is WZR/XZR.
        family = word & 0xFFC00000
        if family in (0xB9400000, 0xB9000000, 0xF9400000, 0xF9000000):
            width = 8 if word & 0x40000000 else 4
            load = bool(word & 0x00400000)
            rt, rn = word & 31, (word >> 5) & 31
            offset = ((word >> 10) & 0xFFF) * width
            base = "s->sp" if rn == 31 else f"s->x[{rn}]"
            lines.append("    {")
            lines.append(f"        uint64_t addr = {base} + 0x{offset:x}ULL;")
            if load:
                lines.append("        uint64_t value;")
                lines.append(f"        if (!mario_read(s, addr, {width}, &value)) {{ s->fault = 1; return; }}")
                if rt != 31:
                    lines.append(f"        s->x[{rt}] = value;")
            else:
                value = "0ULL" if rt == 31 else f"s->x[{rt}]"
                lines.append(f"        if (!mario_write(s, addr, {width}, {value})) {{ s->fault = 1; return; }}")
            lines.append("    }")
            continue

        # Register-offset LDR/STR (LSL Xm or UXTW Wm), W/X only.
        # Reject other extend options and writeback forms.
        if (word & 0xFFE00C00) in (0xB8600800, 0xB8200800,
                                   0xF8600800, 0xF8200800):
            option = (word >> 13) & 7
            if option not in (2, 3):
                return None
            width = 8 if word & 0x40000000 else 4
            load = bool(word & 0x00400000)
            rt, rn, rm = word & 31, (word >> 5) & 31, (word >> 16) & 31
            base = "s->sp" if rn == 31 else f"s->x[{rn}]"
            index = "0ULL" if rm == 31 else f"s->x[{rm}]"
            if option == 2:
                index = f"(uint32_t)({index})"
            shift = (3 if width == 8 else 2) if word & 0x1000 else 0
            lines.append("    {")
            lines.append(f"        uint64_t addr = {base} + ((uint64_t)({index}) << {shift});")
            if load:
                lines.append("        uint64_t value;")
                lines.append(f"        if (!mario_read(s, addr, {width}, &value)) {{ s->fault = 1; return; }}")
                if rt != 31:
                    lines.append(f"        s->x[{rt}] = value;")
            else:
                value = "0ULL" if rt == 31 else f"s->x[{rt}]"
                lines.append(f"        if (!mario_write(s, addr, {width}, {value})) {{ s->fault = 1; return; }}")
            lines.append("    }")
            continue

        # Signed scaled-offset STP/LDP, W/X general-purpose registers only.
        # Pre/post-index and SIMD variants remain unsupported.
        family = word & 0xFFC00000
        if family in (0x29000000, 0x29400000, 0xA9000000, 0xA9400000):
            width = 8 if word & 0x80000000 else 4
            load = bool(word & 0x00400000)
            rt, rt2, rn = word & 31, (word >> 10) & 31, (word >> 5) & 31
            imm7 = (word >> 15) & 0x7F
            offset = (imm7 - 128 if imm7 & 0x40 else imm7) * width
            base = "s->sp" if rn == 31 else f"s->x[{rn}]"
            lines.append("    {")
            lines.append(f"        uint64_t addr = {base} + (uint64_t)({offset}LL);")
            lines.append("        size_t off0, off1;")
            lines.append(f"        if (!mario_offset(s, addr, {width}, &off0) ||")
            lines.append(f"            !mario_offset(s, addr + {width}ULL, {width}, &off1)) {{")
            lines.append("            s->fault = 1; return;")
            lines.append("        }")
            if load:
                lines.append("        uint64_t value0 = 0, value1 = 0;")
                lines.append(f"        for (size_t i = 0; i < {width}; ++i) {{")
                lines.append("            value0 |= (uint64_t)s->mem[off0 + i] << (8 * i);")
                lines.append("            value1 |= (uint64_t)s->mem[off1 + i] << (8 * i);")
                lines.append("        }")
                if rt != 31:
                    lines.append(f"        s->x[{rt}] = value0;")
                if rt2 != 31:
                    lines.append(f"        s->x[{rt2}] = value1;")
            else:
                value0 = "0ULL" if rt == 31 else f"s->x[{rt}]"
                value1 = "0ULL" if rt2 == 31 else f"s->x[{rt2}]"
                lines.append(f"        uint64_t value0 = {value0}, value1 = {value1};")
                lines.append(f"        for (size_t i = 0; i < {width}; ++i) {{")
                lines.append("            s->mem[off0 + i] = (uint8_t)(value0 >> (8 * i));")
                lines.append("            s->mem[off1 + i] = (uint8_t)(value1 >> (8 * i));")
                lines.append("        }")
            lines.append("    }")
            continue

        return None  # unsupported branch, SIMD, memory mode or system instruction
    return None  # missing RET


def candidates(nso, limit, min_instructions=2, allow_memory=False, use_fde=False):
    """Select bounded candidate spans; optionally prefer validated FDE ranges."""
    funcs, _ = discover(nso)
    starts = sorted(funcs)
    fde_ranges = eh_frame_intervals(nso)[0] if use_fde else {}
    lo, size = nso.text
    hi = lo + size
    count = 0
    for index, start in enumerate(starts):
        end = fde_ranges.get(start, starts[index + 1] if index + 1 < len(starts) else hi)
        span = end - start
        if span < min_instructions * 4 or span > 128 or span % 4:
            continue
        words = struct.unpack_from(f"<{span // 4}I", nso.image, start)
        if not allow_memory and any((w & 0xFFC00000) in
                (0xB9400000, 0xB9000000, 0xF9400000, 0xF9000000,
                 0x29000000, 0x29400000, 0xA9000000, 0xA9400000)
                for w in words):
            continue
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
    parser.add_argument("--with-memory", action="store_true",
                        help="include bounded 32/64-bit LDR/STR and offset LDP/STP functions")
    parser.add_argument("--use-fde", action="store_true",
                        help="use validated FDE spans when available (experimental)")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if not 1 <= args.min_instructions <= 32:
        parser.error("--min-instructions must be between 1 and 32")
    nso = Nso(args.nso)
    matches = list(candidates(nso, args.limit, args.min_instructions,
                              allow_memory=args.with_memory, use_fde=args.use_fde))
    if not matches:
        raise SystemExit("No functions match the conservative instruction subset; no C emitted")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(matches), encoding="utf-8")
    print(f"Generated {len(matches)} stateful leaf candidates: {args.output}")
    for start, end, _ in matches:
        print(f"  0x{start:x}..0x{end:x}")


if __name__ == "__main__":
    main()
