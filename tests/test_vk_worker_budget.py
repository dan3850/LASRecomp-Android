#!/usr/bin/env python3
"""Portable worker-budget regressions, independent of a Vulkan SDK or game files."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="las-vk-workers-") as tmp:
    for cc in [os.environ.get("CC", "cc")]:
        exe = Path(tmp) / "test"
        subprocess.run([cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/vk_worker_budget_test.c"), "-o", str(exe)],
                       check=True, cwd=ROOT)
        subprocess.run([str(exe)], check=True, cwd=ROOT)
