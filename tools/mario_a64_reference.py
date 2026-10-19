"""Independent tiny AArch64 reference interpreter for restricted Mario leaf tests.

It is intentionally separate from the C code generator. Supports only NOP,
RET X30, move-wide immediates, ADD/SUB immediate and bounded LDR/STR. Invalid
or unsupported guest instruction encodings cause a hard error.
This is an *approximate secondary oracle*, not a substitute for Unicorn.
"""
import struct

MASK64 = (1 << 64) - 1


def run_reference(code, initial, ram=None, ram_base=0):
    if not code or len(code) % 4:
        raise ValueError("AArch64 code must contain whole 4-byte instructions")
    regs = [int(initial.x[i]) for i in range(31)]
    stack = int(initial.sp)
    nzcv = int(initial.nzcv) & 0xF0000000
    words = struct.unpack("<" + "I" * (len(code) // 4), code)

    for index, op in enumerate(words):
        if op == 0xD503201F:
            continue
        if op == 0xD65F03C0:
            if index != len(words) - 1:
                raise ValueError("Early RET cannot be interpreted as a leaf")
            return (tuple(regs), stack, regs[30], nzcv)

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

        # Independent decode for unsigned-offset 32/64-bit LDR/STR.
        # Memory is a caller-provided bytearray, never a raw host address.
        family = op & 0xFFC00000
        if family in (0xB9400000, 0xB9000000, 0xF9400000, 0xF9000000):
            width = 8 if (op >> 30) & 1 else 4
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

        raise ValueError(f"Unsupported instruction: {op:08x}")

    raise ValueError("No final RET")


__all__ = ["run_reference"]
