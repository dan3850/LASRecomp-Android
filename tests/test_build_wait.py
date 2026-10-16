#!/usr/bin/env python3
"""Production shader completion gate, Android and desktop policies, no GPU required."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="las-build-wait-") as tmp:
    for android in (False, True):
        exe = Path(tmp) / ("android" if android else "desktop")
        flags = ["-D__ANDROID__"] if android else []
        if os.environ.get("SANITIZE"):
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O1", "-g",
            *flags, str(ROOT / "tests/build_wait_test.c"), "-lpthread", "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=10)
