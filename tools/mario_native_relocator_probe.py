#!/usr/bin/env python3
"""Prototype AArch64 RELA relocator with strictly synthetic tests.

No Nintendo files are opened or emitted by this module.
The implementation is intentionally not yet a game loader: symbol resolution,
segment protections, TLS and SVC compatibility remain outside this test.
"""
import argparse
import struct

ABS64 = 257
GLOB_DAT = 1025
JUMP_SLOT = 1026
RELATIVE = 1027
MASK64 = (1 << 64) - 1


class RelocationError(ValueError):
    pass


def apply_relocations(image, base, relocs, symbols, resolver):
    """Apply checked (offset, type, sym_index, addend) entries to bytearray.

    symbols: (name, section, value) tuples. Undefined names go through resolver.
    For RELATIVE, B + A. ABS64 uses S + A; GLOB_DAT and JUMP_SLOT use S + A
    according to AArch64 ELF64 RELA semantics. All writes are 64-bit LE.
    """
    if not isinstance(image, bytearray):
        raise RelocationError("image must be a private writable bytearray")
    if not (0 <= base <= MASK64):
        raise RelocationError("invalid base")
    writes = []
    for offset, kind, index, addend in relocs:
        if offset < 0 or offset & 7 or offset + 8 > len(image):
            raise RelocationError(f"invalid relocation destination {offset:#x}")
        if kind == RELATIVE:
            if index != 0:
                raise RelocationError("RELATIVE with nonzero symbol index")
            value = base + addend
        elif kind in (ABS64, GLOB_DAT, JUMP_SLOT):
            if not (0 <= index < len(symbols)):
                raise RelocationError("relocation symbol index out of bounds")
            name, section, sym_value = symbols[index]
            if section:
                if not (0 <= sym_value < len(image)):
                    raise RelocationError(f"symbol outside image: {name}")
                symbol_address = base + sym_value
            else:
                symbol_address = resolver(name)
                if symbol_address is None:
                    raise RelocationError(f"unresolved import: {name}")
            value = symbol_address + addend
        else:
            raise RelocationError(f"unsupported relocation {kind}")
        if not 0 <= value <= MASK64:
            raise RelocationError(f"64-bit relocation overflow at {offset:#x}")
        writes.append((offset, value))
    # Validate everything before modifying the image.
    for offset, value in writes:
        struct.pack_into("<Q", image, offset, value)
    return len(writes)


def self_test():
    main_base = 0x7000000000
    sdk_base = 0x7002000000
    main = bytearray(128)
    sdk = bytearray(128)
    main_symbols = [
        ("", 0, 0),
        ("internal_main", 1, 0x50),
        ("external_sdk", 0, 0),
    ]
    sdk_symbols = [
        ("", 0, 0),
        ("external_sdk", 1, 0x60),
        ("internal_main", 0, 0),
    ]
    main_relocs = [
        (0, RELATIVE, 0, 0x40),
        (8, ABS64, 1, 3),
        (16, GLOB_DAT, 2, 0),
        (24, JUMP_SLOT, 2, 8),
    ]
    sdk_relocs = [
        (0, RELATIVE, 0, 0x30),
        (8, ABS64, 1, 0),
        (16, GLOB_DAT, 2, 0),
        (24, JUMP_SLOT, 2, 4),
    ]
    # In a real loader, these mappings must come from validated exports/HLE.
    exports = {"external_sdk": sdk_base + 0x60, "internal_main": main_base + 0x50}
    assert apply_relocations(main, main_base, main_relocs, main_symbols, exports.get) == 4
    assert apply_relocations(sdk, sdk_base, sdk_relocs, sdk_symbols, exports.get) == 4
    actual_main = struct.unpack_from("<4Q", main)
    actual_sdk = struct.unpack_from("<4Q", sdk)
    assert actual_main == (
        main_base + 0x40, main_base + 0x53,
        sdk_base + 0x60, sdk_base + 0x68), actual_main
    assert actual_sdk == (
        sdk_base + 0x30, sdk_base + 0x60,
        main_base + 0x50, main_base + 0x54), actual_sdk

    bad = bytearray(64)
    before = bytes(bad)
    try:
        apply_relocations(
            bad, main_base,
            [(0, RELATIVE, 0, 8), (8, JUMP_SLOT, 2, 0)],
            main_symbols, lambda name: None
        )
    except RelocationError as e:
        assert "unresolved" in str(e)
    else:
        raise AssertionError("unresolved import was accepted")
    assert bytes(bad) == before, "failed transaction modified image"

    for rejected in (
        [(3, RELATIVE, 0, 0)],
        [(64, RELATIVE, 0, 0)],
        [(0, RELATIVE, 1, 0)],
        [(0, 9999, 0, 0)],
    ):
        try:
            apply_relocations(bytearray(64), main_base, rejected, main_symbols, exports.get)
        except RelocationError:
            pass
        else:
            raise AssertionError(f"invalid relocation accepted: {rejected}")
    print("PASS: synthetic main/sdk ARM64 ABS64 GLOB_DAT JUMP_SLOT RELATIVE relocations (8 writes).")
    print("PASS: external symbol resolution, 64-bit values, bounds and atomic failure.")
    print("SCOPE: no real NSO image mapped or executed; import policy/TLS/SVC/x18 not implemented.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true", required=True)
    p.parse_args()
    self_test()


if __name__ == "__main__":
    main()
