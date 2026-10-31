#!/usr/bin/env python3
"""Read-only verification of the prepared 2026 Android source baseline."""
from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: auditar_build_scarletnx_2026.py SOURCE")
src = Path(sys.argv[1]).expanduser().resolve()
expected = "05324b57629d0894506b31beb2c72869138b7ad1"
actual = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
if actual != expected:
    raise SystemExit("INCOMPATIVEL: ScarletNX revision " + actual)
checks = {
    "LLVM Android Termux branch": ("cmake/llvm.cmake", "if((ANDROID AND NOT SNX_TERMUX_NATIVE_LLVM) OR IOS OR (LLVM_DIR AND NOT SNX_LLVM_CONFIG))"),
    "LLVM shared component libraries": ("cmake/llvm.cmake", "snx_llvm_query(SNX_LLVM_LIBS --link-shared --libs ${SNX_LLVM_COMPONENTS})"),
    "LLVM shared A64 disassembler": ("cmake/llvm.cmake", "snx_llvm_query(SNX_LLVM_DISASM_LIBS --link-shared --libs aarch64disassembler aarch64desc aarch64info)"),
    "FFmpeg Android configuration": ("cmake/ffmpeg.cmake", "if(ANDROID)\n    # the NDK's Clang takes its target and sysroot as flags"),
    "OpenSSL Android compiler PATH": ("cmake/openssl.cmake", '"PATH=${ANDROID_TOOLCHAIN_ROOT}/bin:$ENV{PATH}"'),
    "RomFS external graft": ("src/nx/hle/filesystem/fs.c", 'const char* external_romfs = getenv("SNX_EXTERNAL_ROMFS");'),
    "RomFS upstream initialization": ("src/nx/hle/filesystem/fs.c", 'fs_tree_init_skipping(&g_hle.fs.tree, g_datadir, apart)'),
}
failed = 0
for label, (name, needle) in checks.items():
    path = src / name
    ok = path.is_file() and path.read_text(errors="replace").count(needle) == 1
    print(f"{'OK' if ok else 'INCOMPATIVEL'}: {label} [{name}]")
    failed += not ok
print(f"Prepared source checks: {len(checks)-failed}/{len(checks)}")
print("Read-only check; this does not validate native linking or APK boot.")
sys.exit(bool(failed))
