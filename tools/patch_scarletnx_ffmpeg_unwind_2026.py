#!/usr/bin/env python3
"""Give FFmpeg's standalone configure the NDK's actual libunwind archive directory."""
from pathlib import Path
import subprocess
import sys
if len(sys.argv) != 3:
    raise SystemExit("Usage: patch_scarletnx_ffmpeg_unwind_2026.py SOURCE LIBUNWIND_DIR")
src = Path(sys.argv[1]).resolve()
libdir = Path(sys.argv[2]).resolve()
if subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip() != "05324b57629d0894506b31beb2c72869138b7ad1":
    raise SystemExit("Unexpected ScarletNX revision")
if not (libdir / "libunwind.a").is_file():
    raise SystemExit("libunwind.a not found in " + str(libdir))
if any(x in str(libdir) for x in ('"', ';', '$', '\n', '\r', '\\', ' ')):
    raise SystemExit("Unsupported path")
path = src / "cmake/ffmpeg.cmake"
data = path.read_text()
old = '         --extra-ldflags=--target=${CMAKE_C_COMPILER_TARGET} --enable-pic)'
new = '         "--extra-ldflags=--target=${CMAKE_C_COMPILER_TARGET} -L' + str(libdir) + '" --enable-pic)'
if data.count(old) == 1:
    data = data.replace(old, new)
elif data.count(new) != 1:
    raise SystemExit("FFmpeg Android linker anchor changed")
path.write_text(data)
print("FFMPEG_UNWIND_PATCH_OK: " + str(libdir))
