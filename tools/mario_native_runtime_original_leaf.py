#!/usr/bin/env python3
"""Call VERIFIED original Mario ARM64 leaf through runtime x18-safe entry.

This integrates the already validated real-address two-NSO relocator with
runtime/mario_native_thread_entry.S compiled into a host shared library.
Only the exact original MOVZ W0/X0,#5 ; RET at offset 0x92BA0 may run.
No SVC, TLS, host callbacks, or arbitrary function entries are permitted.
"""
import argparse
import ctypes
import platform
from pathlib import Path
import sys

from nso import Nso
from mario_native_mapped_image_probe import TESTED_OFFSET, verify_leaf
from mario_native_relocated_mapping_probe import (
    boundaries, map_rw, protect_executable_text, relocate_module
)
from mario_native_real_reloc_probe import exports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("entry_library", type=Path)
    args = parser.parse_args()
    if sys.platform not in ("linux", "android") or platform.machine().lower() not in ("aarch64", "arm64"):
        raise RuntimeError("native ARM64 Android/Termux required")
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    modules = {name: Nso(root / name) for name in ("main", "sdk")}
    expected = verify_leaf(modules["main"])
    bridge = ctypes.CDLL(str(args.entry_library.resolve()))
    invoke = bridge.mario_native_call_leaf
    invoke.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64)
    invoke.restype = ctypes.c_uint64
    mappings = {}
    try:
        for name in ("main", "sdk"):
            mappings[name] = map_rw(modules[name])
        symbol_tables = {
            name: exports(modules[name], mappings[name][1]) for name in modules
        }
        for name in ("main", "sdk"):
            region, base = mappings[name]
            other = "sdk" if name == "main" else "main"
            symbols, conflicts = symbol_tables[other]
            resolved = dict(symbols)
            resolved.update(boundaries(modules[name], base))
            patched, count, remaining = relocate_module(
                modules[name], base, resolved, conflicts
            )
            region[:modules[name].size] = patched
            print(f"{name}: relocated={count} unresolved={sum(remaining.values())}", flush=True)
            if (name == "main" and sum(remaining.values()) != 8) or (
                name == "sdk" and sum(remaining.values()) != 2
            ):
                raise RuntimeError("unexpected unresolved relocation count")
        for name in modules:
            protect_executable_text(modules[name], mappings[name][1])
        _, base = mappings["main"]
        entry = base + TESTED_OFFSET
        # The original leaf does not read x18 or x0 input. The guest x18 value
        # here is a harmless test sentinel, NOT a Switch TLS pointer.
        for iteration in range(64):
            actual = invoke(entry, None, 0x2750)
            if actual != expected:
                raise RuntimeError(
                    f"iteration {iteration}: returned {actual}, expected {expected}"
                )
        print(f"PASS: ORIGINAL Mario main ARM64 at {TESTED_OFFSET:#x} executed 64 times through runtime x18 entry; return={expected}.")
        print("PASS: main/sdk privately mapped with actual Android addresses and verified relocations.")
        print("LIMITS: precise MOVZ+RET only; no guest x18/TLS access, no SVC bridge, no game boot.")
        print("INPUTS UNCHANGED: local original files and APK untouched.")
    finally:
        for region, _ in mappings.values():
            region.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, AssertionError, ImportError) as error:
        raise SystemExit(f"ERROR: {error}")
