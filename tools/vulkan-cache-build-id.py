#!/usr/bin/env python3
"""Content identity for persistent Vulkan resources; keep unchanged headers' mtimes."""
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
paths = set()
for folder in ["runtime/nvn/vulkan", "runtime/nvn/maxwell"]:
    for path in (ROOT / folder).iterdir():
        if path.suffix in {".h", ".c", ".cpp"}:
            paths.add(path)
for name in ["runtime/nvn/nvn.h", "runtime/nvn/renderer.h", "runtime/nvn/formats.c",
             "runtime/settings.h", "compilar-lasrecomp-termux.sh", "tools/build-android-renderer.sh",
             "tools/vulkan-cache-build-id.py"]:
    paths.add(ROOT / name)
digest = hashlib.sha256()
for path in sorted(paths):
    name, data = path.relative_to(ROOT).as_posix().encode(), path.read_bytes()
    digest.update(len(name).to_bytes(4, "little")); digest.update(name)
    digest.update(len(data).to_bytes(8, "little")); digest.update(data)
text = ('// Generated from Vulkan/translator sources and build recipes.\n#pragma once\n'
        '#define LAS_VK_CACHE_PERSISTENT 1\n'
        f'#define LAS_VK_CACHE_BUILD_ID "{digest.hexdigest()}"\n')
args.output.parent.mkdir(parents=True, exist_ok=True)
if not args.output.exists() or args.output.read_text() != text:
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(args.output)
