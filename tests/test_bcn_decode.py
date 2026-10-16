#!/usr/bin/env python3
"""BCn fallback pixel values, signed/HDR channels, cropping, slices and bounds."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="las-bcn-") as tmp:
    exe = Path(tmp) / "bcn-test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if os.environ.get("SANITIZE") else []
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O1", "-g", *flags,
                    str(ROOT / "tests/bcn_decode_test.c"), str(ROOT / "runtime/nvn/bcn_decode.c"),
                    "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
