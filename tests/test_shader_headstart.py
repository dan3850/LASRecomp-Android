#!/usr/bin/env python3
"""Exercise the imported NVN shader-variant grammar without game files or Vulkan."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="las-shader-headstart-") as tmp:
    binary = Path(tmp) / "records"
    compiler = os.environ.get("CC", "cc")
    subprocess.run([compiler, "-std=gnu11", "-O1", "-Wall", "-Wextra",
                    "-pthread", "-I", str(root / "runtime"),
                    str(root / "tests/shader_headstart_records_test.c"),
                    str(root / "runtime/nvn/shader_prep.c"),
                    "-o", str(binary)], cwd=root, check=True)
    subprocess.run([str(binary)], cwd=root, check=True)
