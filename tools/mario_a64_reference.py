"""Independent tiny AArch64 reference interpreter for restricted Mario leaf tests.

It is intentionally separate from the C code generator. Supports only NOP,
RET X30, move-wide immediates, ADD/SUB immediate and bounded LDR/STR and signed-offset LDP/STP. Invalid
or unsupported guest instruction encodings cause a hard error.
This is an *approximate secondary oracle*, not a substitute for Unicorn.
"""
import struct

MASK64 = (1 << 64) - 1

def levels_mask(bits):
    return (1 << bits) - 1


def run_reference(code, initial, ram=None, ram_base=0):
    if not code or len(code) % 4:
        raise ValueError("AArch64 code must contain whole 4-byte instructions")
    regs = [int(initial.x[i]) for i in range(31)]
    stack = int(initial.sp)
    nzcv = int(initial.nzcv) & 0xF0000000
    words = struct.unpack("<" + "I" * (len(code) // 4), code)

    index = 0
    while index < len(words):
        op = words[index]
        index += 1
        if (op & 0xFC000000) == 0x14000000:
            imm = op & 0x03FFFFFF
            displacement = imm - 0x04000000 if imm & 0x02000000 else imm
            target = index - 1 + displacement
            if target < index or target >= len(words):
                raise ValueError("Unsupported backward or external B")
            index = target
            continue
        if (op & 0x7E000000) == 0x36000000:
            imm = (op >> 5) & 0x3FFF
            displacement = imm - 0x4000 if imm & 0x2000 else imm
            target = index - 1 + displacement
            if target < index or target >= len(words):
                raise ValueError("Unsupported backward or external TBZ/TBNZ")
            rt = op & 31
            bit = ((op >> 31) << 5) | ((op >> 19) & 31)
            value = 0 if rt == 31 else regs[rt]
            bit_set = bool(value & (1 << bit))
            if bit_set == bool(op & 0x01000000):
                index = target
            continue
        if (op & 0xFF000010) == 0x54000000:
            cond = op & 15
            imm = (op >> 5) & 0x7FFFF
            displacement = imm - 0x80000 if imm & 0x40000 else imm
            target = index - 1 + displacement
            if cond >= 14 or target < index or target >= len(words):
                raise ValueError("Unsupported B.cond encoding or destination")
            n, z = bool(nzcv & (1 << 31)), bool(nzcv & (1 << 30))
            carry, overflow = bool(nzcv & (1 << 29)), bool(nzcv & (1 << 28))
            conditions = (z, not z, carry, not carry, n, not n,
                          overflow, not overflow, carry and not z,
                          not carry or z, n == overflow, n != overflow,
                          not z and n == overflow, z or n != overflow)
            if conditions[cond]:
                index = target
            continue
        if (op & 0x7E000000) == 0x34000000:
            imm = (op >> 5) & 0x7FFFF
            displacement = imm - 0x80000 if imm & 0x40000 else imm
            target = index - 1 + displacement
            if target < index or target >= len(words):
                raise ValueError("Unsupported backward or external CBZ/CBNZ")
            rt = op & 31
            value = 0 if rt == 31 else regs[rt]
            if not (op & 0x80000000):
                value &= 0xFFFFFFFF
            take = (value != 0) if op & 0x01000000 else (value == 0)
            if take:
                index = target
            continue
        if op == 0xD503201F:
            continue
        if op == 0xD65F03C0:
            if index != len(words):
                raise ValueError("Early RET cannot be interpreted as a leaf")
            return (tuple(regs), stack, regs[30], nzcv)

        # MOV register alias: ORR Rd, ZR, Rm, LSL #0.
        if (op & 0x7FE0FFE0) == 0x2A0003E0:
            dest, source = op & 31, (op >> 16) & 31
            if dest != 31:
                value = 0 if source == 31 else regs[source]
                regs[dest] = value if op & 0x80000000 else value & 0xFFFFFFFF
            continue

        # ADR/ADRP: derive effective address using guest instruction PC,
        # not the host's code address or the NSO file offset.
        if (op & 0x1F000000) == 0x10000000:
            imm = ((op >> 29) & 3) | (((op >> 5) & 0x7FFFF) << 2)
            if imm & 0x100000:
                imm -= 0x200000
            address = (int(initial.pc) + (index - 1) * 4) & MASK64
            if op & 0x80000000:
                address &= ~0xFFF
                imm *= 4096
            rd = op & 31
            if rd != 31:
                regs[rd] = (address + imm) & MASK64
            continue

        # AArch64 move-wide immediate encoding (32/64 bit, shift 0..48).
        move_class = (op >> 23) & 0x3F
        if move_class == 0b100101:
            is_64 = bool(op & (1 << 31))
            op_field = (op >> 29) & 0b11
            if op_field == 0b01:
                raise ValueError("Reserved move-wide operation")
            half = (op >> 21) & 0b11
            if not is_64 and half >= 2:
                raise ValueError("Reserved 32-bit move-wide shift")
            dest = op & 31
            imm = (op >> 5) & 0xFFFF
            value = imm << (16 * half)
            mask = MASK64 if is_64 else 0xFFFFFFFF
            if dest != 31:
                if op_field == 0b00:  # MOVN
                    result = ~value
                elif op_field == 0b10:  # MOVZ
                    result = value
                elif op_field == 0b11:  # MOVK
                    keep = mask ^ (0xFFFF << (16 * half))
                    result = (regs[dest] & keep) | value
                else:
                    raise ValueError("Reserved move-wide op")
                regs[dest] = result & mask
            continue

        # Logical immediate: independently reconstruct replicated rotated bitmask.
        if (op & 0x1F800000) == 0x12000000:
            width = 64 if op & (1 << 31) else 32
            opc = (op >> 29) & 3
            n = (op >> 22) & 1
            immr = (op >> 16) & 63
            imms = (op >> 10) & 63
            if width == 32 and n:
                raise ValueError("Invalid 32-bit logical immediate")
            length = ((n << 6) | (63 ^ imms)).bit_length() - 1
            if length < 1:
                raise ValueError("Invalid logical immediate")
            size = 1 << length
            levels = size - 1
            ones = imms & levels
            if ones == levels:
                raise ValueError("Reserved logical immediate")
            pattern = (1 << (ones + 1)) - 1
            rotate = immr & levels
            pattern = ((pattern >> rotate) | (pattern << (size - rotate))) & levels_mask(size)
            mask = sum(pattern << pos for pos in range(0, width, size))
            rd, rn = op & 31, (op >> 5) & 31
            value = (0 if rn == 31 else regs[rn]) & ((1 << width) - 1)
            result = ((value & mask) if opc in (0, 3) else
                      (value | mask) if opc == 1 else (value ^ mask))
            if opc == 3:
                nzcv = (int(bool(result & (1 << (width - 1)))) << 31) | (int(result == 0) << 30)
            elif rd != 31:
                regs[rd] = result
            continue

        # Conditional select/increment, including CSET's CSINC alias.
        family = op & 0x7FE00C00
        if family in (0x1A800000, 0x1A800400):
            cond = (op >> 12) & 15
            if cond >= 14:
                raise ValueError("Unsupported conditional select condition")
            width = 64 if op & (1 << 31) else 32
            rd, rn, rm = op & 31, (op >> 5) & 31, (op >> 16) & 31
            negative = bool(nzcv & 0x80000000)
            zero = bool(nzcv & 0x40000000)
            carry = bool(nzcv & 0x20000000)
            overflow = bool(nzcv & 0x10000000)
            predicates = (zero, not zero, carry, not carry, negative,
                          not negative, overflow, not overflow,
                          carry and not zero, not carry or zero,
                          negative == overflow, negative != overflow,
                          not zero and negative == overflow,
                          zero or negative != overflow)
            source = rn if predicates[cond] else rm
            value = 0 if source == 31 else regs[source]
            if not predicates[cond] and family == 0x1A800400:
                value += 1
            if rd != 31:
                regs[rd] = value & ((1 << width) - 1)
            continue

        # ADD/SUB shifted-register, LSL only, independent arithmetic oracle.
        if (op & 0x1F200000) == 0x0B000000:
            shift_type = (op >> 22) & 3
            amount = (op >> 10) & 63
            width = 64 if op & (1 << 31) else 32
            if shift_type != 0 or amount >= width:
                raise ValueError("Unsupported shifted-register ADD/SUB")
            mask = (1 << width) - 1
            rd, rn, rm = op & 31, (op >> 5) & 31, (op >> 16) & 31
            a = (0 if rn == 31 else regs[rn]) & mask
            b = ((0 if rm == 31 else regs[rm]) << amount) & mask
            subtract = bool(op & (1 << 30))
            setflags = bool(op & (1 << 29))
            result = (a - b if subtract else a + b) & mask
            if setflags:
                sign = 1 << (width - 1)
                negative = bool(result & sign)
                zero = result == 0
                carry = a >= b if subtract else a + b > mask
                overflow = (bool((a ^ b) & (a ^ result) & sign) if subtract
                            else bool((~(a ^ b)) & (a ^ result) & sign))
                nzcv = (int(negative) << 31) | (int(zero) << 30) | (int(carry) << 29) | (int(overflow) << 28)
            if rd != 31:
                regs[rd] = result
            continue

        # ADDS/SUBS immediate; CMP is SUBS with destination XZR/WZR.
        family = op & 0x7F000000
        if family in (0x31000000, 0x71000000):
            shift = (op >> 22) & 3
            if shift > 1:
                raise ValueError("Reserved flag-setting immediate shift")
            width = 64 if op & 0x80000000 else 32
            mask = (1 << width) - 1
            dest, source = op & 31, (op >> 5) & 31
            a = (stack if source == 31 else regs[source]) & mask
            b = ((op >> 10) & 0xFFF) << (12 if shift else 0)
            subtract = family == 0x71000000
            result = (a - b if subtract else a + b) & mask
            sign = 1 << (width - 1)
            n, z = bool(result & sign), result == 0
            carry = a >= b if subtract else a + b > mask
            overflow = (bool((a ^ b) & (a ^ result) & sign) if subtract
                        else bool((~(a ^ b)) & (a ^ result) & sign))
            nzcv = (int(n) << 31) | (int(z) << 30) | (int(carry) << 29) | (int(overflow) << 28)
            if dest != 31:
                regs[dest] = result
            continue

        # ADD/SUB immediate, 32/64 bit, *without* setting flags.
        if ((op >> 24) & 0b11111) == 0b10001 and not (op & (1 << 29)):
            shift = (op >> 22) & 0b11
            if shift >= 2:
                raise ValueError("Reserved ADD/SUB immediate shift")
            width_mask = MASK64 if op & (1 << 31) else 0xFFFFFFFF
            dest = op & 31
            src = (op >> 5) & 31
            left = stack if src == 31 else regs[src]
            imm = ((op >> 10) & 0xFFF) << (12 if shift else 0)
            result = left - imm if op & (1 << 30) else left + imm
            result &= width_mask
            if dest == 31:
                stack = result
            else:
                regs[dest] = result
            continue

        # Independent decode of unsigned-offset byte/halfword/word/doubleword.
        # Memory is a caller-provided bytearray, never a raw host address.
        family = op & 0xFFC00000
        if family in (0x39000000, 0x39400000, 0x79000000, 0x79400000,
                      0xB9400000, 0xB9000000, 0xF9400000, 0xF9000000):
            width = 1 << ((op >> 30) & 3)
            load = (op >> 22) & 1
            rt, rn = op & 31, (op >> 5) & 31
            address = ((stack if rn == 31 else regs[rn])
                       + ((op >> 10) & 0xFFF) * width) & MASK64
            offset = address - ram_base
            if ram is None or offset < 0 or offset + width > len(ram):
                raise MemoryError(f"Guest memory access outside mapped buffer at 0x{address:x}")
            if load:
                value = int.from_bytes(ram[offset:offset + width], "little")
                if rt != 31:
                    regs[rt] = value
            else:
                value = 0 if rt == 31 else regs[rt]
                ram[offset:offset + width] = value.to_bytes(8, "little")[:width]
            continue

        # Register-offset load/store: UXTW or LSL, optional element shift.
        if (op & 0xFFE00C00) in (0xB8600800, 0xB8200800,
                                 0xF8600800, 0xF8200800):
            option = (op >> 13) & 7
            if option not in (2, 3):
                raise ValueError("Unsupported register offset extension")
            width = 8 if op & 0x40000000 else 4
            load = bool(op & 0x00400000)
            rt, rn, rm = op & 31, (op >> 5) & 31, (op >> 16) & 31
            index_value = 0 if rm == 31 else regs[rm]
            if option == 2:
                index_value &= 0xFFFFFFFF
            shift = (3 if width == 8 else 2) if op & 0x1000 else 0
            addr = ((stack if rn == 31 else regs[rn]) +
                    (index_value << shift)) & MASK64
            pos = addr - ram_base
            if ram is None or pos < 0 or pos + width > len(ram):
                raise MemoryError(f"Guest indexed access outside mapped buffer at 0x{addr:x}")
            if load:
                value = int.from_bytes(ram[pos:pos + width], "little")
                if rt != 31:
                    regs[rt] = value
            else:
                value = 0 if rt == 31 else regs[rt]
                ram[pos:pos + width] = value.to_bytes(8, "little")[:width]
            continue

        # LDP/STP general-purpose register pair, signed scaled offset only.
        family = op & 0xFFC00000
        if family in (0x29000000, 0x29400000, 0xA9000000, 0xA9400000):
            width = 8 if (op >> 31) & 1 else 4
            is_load = bool(op & 0x00400000)
            rt = op & 31
            rn = (op >> 5) & 31
            rt2 = (op >> 10) & 31
            imm7 = (op >> 15) & 127
            signed_offset = (imm7 - 128 if imm7 >= 64 else imm7) * width
            addr = ((stack if rn == 31 else regs[rn]) + signed_offset) & MASK64
            pos = addr - ram_base
            if ram is None or pos < 0 or pos + width * 2 > len(ram):
                raise MemoryError(f"Guest pair access outside mapped buffer at 0x{addr:x}")
            if is_load:
                first = int.from_bytes(ram[pos:pos + width], "little")
                second = int.from_bytes(ram[pos + width:pos + width * 2], "little")
                if rt != 31:
                    regs[rt] = first
                if rt2 != 31:
                    regs[rt2] = second
            else:
                first = 0 if rt == 31 else regs[rt]
                second = 0 if rt2 == 31 else regs[rt2]
                ram[pos:pos + width] = first.to_bytes(8, "little")[:width]
                ram[pos + width:pos + width * 2] = second.to_bytes(8, "little")[:width]
            continue

        raise ValueError(f"Unsupported instruction: {op:08x}")

    raise ValueError("No final RET")


__all__ = ["run_reference"]
