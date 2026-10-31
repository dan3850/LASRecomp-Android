#!/usr/bin/env python3
"""Audit exact old-builder assumptions against a new ScarletNX checkout (read only)."""
from pathlib import Path
import re
import sys
if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 tools/auditar_build_scarletnx_2026.py SOURCE")
root = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1]).expanduser().resolve()
builder = (root / "compilar-mario-snx-romfs-termux.sh").read_text()
checks = {
    "LLVM old Android condition": ("cmake/llvm.cmake", "if(ANDROID OR IOS OR (APPLE AND LLVM_DIR AND NOT SNX_LLVM_CONFIG))"),
    "LLVM old component query": ("cmake/llvm.cmake", "snx_llvm_query(SNX_LLVM_LIBS --libs ${SNX_LLVM_COMPONENTS})"),
    "LLVM old disassembler query": ("cmake/llvm.cmake", "snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)"),
    "FFmpeg Android config": ("cmake/ffmpeg.cmake", "if(ANDROID)\n    # the NDK's Clang takes its target and sysroot as flags"),
    "OpenSSL compiler PATH": ("cmake/openssl.cmake", '"PATH=${ANDROID_TOOLCHAIN_ROOT}/bin:$ENV{PATH}"'),
    "RomFS new initialization": ("src/nx/hle/filesystem/fs.c", 'fs_tree_init_skipping(&g_hle.fs.tree, g_datadir, apart)'),
}
failed = 0
for label, (file, needle) in checks.items():
    path = src / file
    ok = path.is_file() and path.read_text(errors="replace").count(needle) == 1
    print(f"{'OK' if ok else 'INCOMPATIVEL'}: {label} [{file}]")
    failed += not ok
print(f"Old build assumptions incompatible: {failed}/{len(checks)}")
print("No source or APK modified. New Android builder requires verified porting.")
sys.exit(1 if failed else 0)
