#!/usr/bin/env python3
"""Port the Termux shared LLVM configuration to ScarletNX 05324b5.

Idempotent. Only touches cmake/llvm.cmake; rejects unknown revisions/layouts.
"""
from pathlib import Path
import subprocess
import sys
REV = "05324b57629d0894506b31beb2c72869138b7ad1"
OLD = "if(ANDROID OR IOS OR (LLVM_DIR AND NOT SNX_LLVM_CONFIG))"
NEW = "if((ANDROID AND NOT SNX_TERMUX_NATIVE_LLVM) OR IOS OR (LLVM_DIR AND NOT SNX_LLVM_CONFIG))"
QUERIES = [
    ("snx_llvm_query(SNX_LLVM_LIBS --libs ${SNX_LLVM_COMPONENTS})",
     "snx_llvm_query(SNX_LLVM_LIBS --link-shared --libs ${SNX_LLVM_COMPONENTS})"),
    ("snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)",
     "snx_llvm_query(SNX_LLVM_DISASM_LIBS --link-shared --libs aarch64disassembler aarch64desc aarch64info)"),
]
if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--check"):
    raise SystemExit("Usage: patch_scarletnx_llvm_2026.py SOURCE [--check]")
src = Path(sys.argv[1]).expanduser().resolve()
revision = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
if revision != REV:
    raise SystemExit("Unexpected ScarletNX revision: " + revision)
path = src / "cmake/llvm.cmake"
data = path.read_text()
if data.count(OLD) + data.count(NEW) != 1:
    raise SystemExit("Unknown LLVM Android condition")
for old, new in QUERIES:
    if data.count(old) + data.count(new) != 1:
        raise SystemExit("Unknown LLVM component query: " + old)
data = data.replace(OLD, NEW, 1)
for old, new in QUERIES:
    data = data.replace(old, new, 1)
if len(sys.argv) == 3:
    print("LLVM_PATCH_CHECK_OK")
else:
    if path.read_text() != data:
        path.write_text(data)
    print("LLVM_PATCH_OK: Termux Android uses shared LLVM via llvm-config")
