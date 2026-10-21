#!/usr/bin/env python3
"""Read-only symbolization of a Mario Android native crash.

Use the exact APK staging copy of liblasrecomp_runtime.so from the Termux
incremental build, not a guessed source file or unrelated shared object.
No compilation, modification of sources, clearing caches or APK installation.
"""
import argparse
import bisect
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys


def parse_text_symbols(output):
    """Extract defined code symbols from llvm-nm --numeric-sort -C output."""
    symbols = []
    for line in output.splitlines():
        match = re.match(r"^([0-9a-fA-F]+)\s+([TtWw])\s+(.+)$", line)
        if match:
            symbols.append((int(match.group(1), 16), match.group(3)))
    return sorted(set(symbols))


def closest_symbol(symbols, address):
    offsets = [off for off, _ in symbols]
    i = bisect.bisect_right(offsets, address) - 1
    return (symbols[i][1], symbols[i][0], address - symbols[i][0]) if i >= 0 else None


def run_tool(argv):
    binary = shutil.which(argv[0])
    if binary is None:
        print(f"UNAVAILABLE: {argv[0]} (not installed/in PATH)")
        return None
    result = subprocess.run([binary, *argv[1:]], text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        print(f"TOOL ERROR: {argv[0]} exit={result.returncode} "
              f"{result.stderr.strip()[:300]}")
        return None
    return result.stdout


def file_hash(file):
    sha = hashlib.sha256()
    with file.open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(data)
    return sha.hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lib", type=Path, default=(
        root / "build/mario-android-boot/stage/lib/arm64-v8a/"
        "liblasrecomp_runtime.so"))
    ap.add_argument("--pc", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--lr", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    lib = args.lib.expanduser().resolve()
    if not lib.is_file() or lib.stat().st_size < 4:
        ap.error(f"APK-stage runtime library not found: {lib}")
    with lib.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            ap.error("not an ELF shared library")
    print(f"LIB={lib}")
    print(f"BYTES={lib.stat().st_size}")
    print(f"SHA256={file_hash(lib)}")
    for text in ("pc", "lr"):
        address = getattr(args, text)
        if address < 0 or address > lib.stat().st_size * 4:
            ap.error(f"implausible module-relative {text} address: {address:#x}")
        print(f"{text.upper()}={address:#x}")

    print("===== ELF BUILD ID / DEBUG AVAILABILITY =====")
    notes = run_tool(["llvm-readelf", "-n", str(lib)])
    if notes:
        for line in notes.splitlines():
            if "Build ID:" in line:
                print(line.strip())
    sections = run_tool(["llvm-readelf", "-S", str(lib)])
    print("DEBUG_INFO=" + ("yes" if sections and ".debug_info" in sections else "no"))

    print("===== SOURCE OR INLINE SYMBOLS (if compiled with debug info) =====")
    for kind in ("pc", "lr"):
        a = getattr(args, kind)
        print(f"--- {kind.upper()} {a:#x} ---")
        out = run_tool(["llvm-addr2line", "-f", "-C", "-i", "-e",
                        str(lib), f"0x{a:x}"])
        print(out.strip() if out else "No debug line information found.")

    print("===== CLOSEST NATIVE SYMBOLS =====")
    nm = run_tool(["llvm-nm", "-n", "-C", "--defined-only", str(lib)])
    if nm is None:
        return 2
    symbols = parse_text_symbols(nm)
    print(f"CODE_SYMBOLS={len(symbols)}")
    for kind in ("pc", "lr"):
        address = getattr(args, kind)
        hit = closest_symbol(symbols, address)
        if hit:
            name, start, delta = hit
            print(f"{kind.upper()} nearest={name} start=0x{start:x} offset=0x{delta:x}")
        else:
            print(f"{kind.upper()} nearest=UNKNOWN (no suitable code symbol)")

    print("===== AARCH64 INSTRUCTIONS NEAR FAULT PC =====")
    pc = args.pc
    asm = run_tool(["llvm-objdump", "-d", "-C",
                    f"--start-address=0x{max(0, pc - 64):x}",
                    f"--stop-address=0x{pc + 96:x}", str(lib)])
    if asm:
        print("\n".join(asm.splitlines()[:120]))
    else:
        print("No disassembly available.")
    print("READ-ONLY: no APK, C sources, objects or caches changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
