#!/usr/bin/env python3
"""Validate the actual Ryujinx C# NativeAOT ELF before bundling it in an APK.

Read-only check; refuses wrong architectures, executables or missing ABI.
Uses llvm-readelf (Termux) and avoids executing the binary at packaging time.
"""
from pathlib import Path
import argparse
import struct
import subprocess
import sys

SONAME = "libRyujinxShaderNative.so"
REQUIRED = ("snx_ryu_api_version", "snx_ryu_translate_v1", "snx_ryu_free_v1")


def validate(path):
    path = Path(path)
    if not path.is_file() or not 1024 <= path.stat().st_size <= 128 * 1024 * 1024:
        raise ValueError("missing or invalid Ryujinx NativeAOT library")
    with path.open("rb") as src:
        head = src.read(64)
    if len(head) < 64 or head[:6] != bytes((127, 69, 76, 70, 2, 1)):
        raise ValueError("expected ELF64 little endian")
    if struct.unpack_from("<H", head, 16)[0] != 3:
        raise ValueError("not an ELF shared library (ET_DYN)")
    if struct.unpack_from("<H", head, 18)[0] != 183:
        raise ValueError("not an Android/ARM64 AArch64 library")
    try:
        symbols = subprocess.check_output(
            ["llvm-readelf", "--dyn-syms", str(path)], text=True, stderr=subprocess.STDOUT)
        dynamic = subprocess.check_output(
            ["llvm-readelf", "-d", str(path)], text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("llvm-readelf unavailable or library not readable") from exc
    for symbol in REQUIRED:
        if not any(symbol in line and "FUNC" in line and "UND" not in line
                   for line in symbols.splitlines()):
            raise ValueError("missing exported ABI symbol: " + symbol)
    # A self-contained NativeAOT library should not depend on the .NET runtime,
    # Termux-only libraries or Linux glibc.
    allowed = {"libc.so", "libdl.so", "libm.so", "liblog.so", "libz.so"}
    for line in dynamic.splitlines():
        if "(NEEDED)" not in line:
            continue
        name = line.split("[", 1)[-1].split("]", 1)[0]
        if name not in allowed:
            raise ValueError("unexpected NativeAOT shared library dependency: " + name)
    print(f"RYUJINX_NATIVE_ELF_OK: Android ARM64, ABI 1 ({path.stat().st_size} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("library", type=Path)
    args = ap.parse_args()
    try:
        validate(args.library)
    except (OSError, ValueError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
