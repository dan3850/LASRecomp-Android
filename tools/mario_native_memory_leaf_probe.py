#!/usr/bin/env python3
"""Run a verified ORIGINAL Mario ARM64 load+return sequence inside mapped NSOs.

Only narrowly allowed leaf instruction forms:
  LDR W0/X0, literal ; RET
  ADRP X0 ; LDR W0/X0, [X0, #unsigned-offset] ; RET
The effective read must lie wholly inside the NSO rodata/data segment.
No SVC, TLS, x18, indirect guest calls, code patching or game startup.
If no such sequence exists, report NOT_FOUND rather than guessing.
"""
import argparse
import ctypes
import mmap
import platform
import struct
import sys
from pathlib import Path

from nso import Nso
from mario_native_mapped_image_probe import TESTED_BUILD_ID
from mario_native_relocated_mapping_probe import (
    map_rw, relocate_module, boundaries, protect_executable_text
)
from mario_native_real_reloc_probe import exports


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def candidate(nso):
    lo, size = nso.text
    end = lo + size
    # Require the read to be in immutable rodata or initialized data.
    allowed = [nso.rodata, nso.data]
    for pc in range(lo, end - 12, 4):
        first = nso.u32(pc)
        second = nso.u32(pc + 4)
        third = nso.u32(pc + 8)
        choices = []
        # LDR W0/X0, PC-relative literal. Operand register must be X0/W0.
        if second == 0xD65F03C0 and (first & 0xFF00001F) in (0x18000000, 0x58000000):
            width = 8 if first & 0x40000000 else 4
            displacement = signed((first >> 5) & 0x7FFFF, 19) * 4
            choices.append((pc + displacement, width, 8, "LDR_LITERAL"))
        # ADRP X0 ; LDR X0/W0, [X0, #uimm12 * width] ; RET
        if third == 0xD65F03C0 and first & 0x9F00001F == 0x90000000:
            if second & 0xFFC003FF in (0xB9400000, 0xF9400000):
                width = 8 if second & 0x40000000 else 4
                immlo = (first >> 29) & 3
                immhi = (first >> 5) & 0x7FFFF
                page_delta = signed((immhi << 2) | immlo, 21) << 12
                offset = (pc & ~0xFFF) + page_delta + ((second >> 10) & 0xFFF) * width
                choices.append((offset, width, 12, "ADRP_LDR"))
        for target, width, count, kind in choices:
            if target < 0 or target + width > len(nso.image):
                continue
            if not any(s <= target and target + width <= s + n for s, n in allowed):
                continue
            # No relocation writes within the original load source location.
            if any(not (r_off + 8 <= target or target + width <= r_off)
                   for r_off, _, _, _ in nso.relocs):
                continue
            original = int.from_bytes(nso.image[target:target + width], "little")
            return pc, target, width, count, kind, original
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game", type=Path)
    args = ap.parse_args()
    if sys.platform not in ("android", "linux") or platform.machine().lower() not in ("aarch64", "arm64"):
        raise RuntimeError("Android/Termux ARM64 required")
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    modules = {name: Nso(root / name) for name in ("main", "sdk")}
    if modules["main"].build_id != TESTED_BUILD_ID:
        raise RuntimeError("main Build ID changed; refusing to execute unvalidated code")
    selected = None
    for name in ("main", "sdk"):
        found = candidate(modules[name])
        if found:
            selected = (name, found)
            break
    if selected is None:
        print("NOT_FOUND: no verified original load+RET sequence was found; nothing executed.")
        return

    name, (pc, target, width, length, kind, expected) = selected
    print(f"FOUND: {name} kind={kind} offset={pc:#x} read={target:#x} width={width} expected={expected:#x}", flush=True)
    mappings = {}
    try:
        for item in ("main", "sdk"):
            mappings[item] = map_rw(modules[item])
        module_exports = {item: exports(modules[item], mappings[item][1])
                          for item in ("main", "sdk")}
        for item in ("main", "sdk"):
            region, base = mappings[item]
            other = "sdk" if item == "main" else "main"
            resolver, conflicts = module_exports[other]
            named = dict(resolver)
            named.update(boundaries(modules[item], base))
            patched, count, pending = relocate_module(modules[item], base, named, conflicts)
            region[:modules[item].size] = patched
            print(f"{item}: relocated={count} pending={sum(pending.values())}", flush=True)
        for item in ("main", "sdk"):
            protect_executable_text(modules[item], mappings[item][1])
        region, base = mappings[name]
        runtime_expected = int.from_bytes(region[target:target + width], "little")
        if runtime_expected != expected:
            raise RuntimeError("read target changed after relocation")
        fn = ctypes.CFUNCTYPE(ctypes.c_uint64)(base + pc)
        result = fn()
        if result != expected:
            raise RuntimeError(f"native memory-read return mismatch: {result:#x} vs {expected:#x}")
        print(f"PASS: original {name} {kind} loaded real mapped NSO memory and returned {result:#x}.")
        print("SCOPE: one verified load+return sequence; no game boot, SVC, TLS, x18, or glslc/nnos implemented.")
        print("INPUTS UNCHANGED: private mappings only, no ROM or APK modifications.")
    finally:
        for region, _ in mappings.values():
            region.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, AssertionError, ImportError) as e:
        raise SystemExit(f"ERROR: {e}")
