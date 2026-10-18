#!/usr/bin/env python3
"""Standalone regression for Vulkan guest-copy cache policy (no game or Vulkan SDK needed)."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="las-vk-gcopy-") as folder:
    binary = Path(folder) / "test"
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2", "-Wall",
                    "-Wextra", "-Werror", str(root / "tests/vk_guest_copy_test.c"),
                    "-o", str(binary)], check=True, cwd=root)
    subprocess.run([str(binary)], check=True, cwd=root)
