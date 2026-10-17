#!/usr/bin/env python3
"""Stable, conservative shader/pipeline ABI identity for persistent Vulkan replay.

This intentionally excludes graphics execution, GMEM streaming, render targets,
memory residency, Android packaging and other performance-only implementation
details. Their changes must not discard recorded shader/pipeline recipes.

Only changes in the shader translator, shader module compiler, pipeline
creation/validation, replay protocol, and related structure definitions
invalidate the cache. The replay identity also includes device, driver, Vulkan
pipeline-cache UUID, enabled features and PIPE_STATE_SIZE at runtime.
"""
import argparse
import hashlib
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
TRACKED = (
    "runtime/nvn/vulkan/shaders.c",
    "runtime/nvn/vulkan/shaders.h",
    "runtime/nvn/vulkan/replay.c",
    "runtime/nvn/vulkan/replay.h",
    "runtime/nvn/vulkan/cache_identity.h",
    "runtime/nvn/vulkan/vk.h",
    "runtime/nvn/nvn.h",
    "runtime/nvn/formats.c",
    "tools/vulkan-cache-build-id.py",
)
# The graphics pipeline compiler and CPU->SPIR-V shader preparation live in
# exec.c, alongside thousands of lines of unrelated memory/copy/dispatch code.
# Extract the exact ABI-sensitive regions instead of hashing all of exec.c.
EXEC_REGIONS = (
    ("// ================================================================== programs",
     "// ================================================================== vertex formats / fixed function tables"),
    ("// ================================================================== vertex formats / fixed function tables",
     "// ================================================================== graphics pipelines"),
    ("// ================================================================== graphics pipelines",
     "// ================================================================== feedback snapshots"),
    ("static VkResult build_compute_raw(",
     "static void build_compute("),
    ("static bool pipeline_recipe_state(",
     "static struct CsEnt"),
)

def parts(root: Path):
    for name in TRACKED:
        path = root / name
        yield name, path.read_bytes()
    shader_dir = root / "runtime/nvn/maxwell"
    for path in sorted(shader_dir.iterdir()):
        if path.suffix in {".h", ".c", ".cpp"}:
            yield path.relative_to(root).as_posix(), path.read_bytes()
    source = (root / "runtime/nvn/vulkan/exec.c").read_bytes()
    for start, stop in EXEC_REGIONS:
        a = source.find(start.encode())
        b = source.find(stop.encode())
        if a < 0 or b < a or source.find(start.encode(), a + 1) >= 0:
            raise ValueError(f"Pipeline ABI marker missing or duplicated: {start}")
        yield "runtime/nvn/vulkan/exec.c@" + start, source[a:b]

def digest_root(root: Path) -> str:
    h = hashlib.sha256()
    h.update(b"LASRecomp VK pipeline recipe ABI v2\0")
    for name, data in parts(root):
        encoded = name.encode()
        h.update(len(encoded).to_bytes(4, "little"))
        h.update(encoded)
        h.update(len(data).to_bytes(8, "little"))
        h.update(data)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--root", default=DEFAULT_ROOT, type=Path,
                    help="Source checkout (for isolated tests); defaults to tool location")
    args = ap.parse_args()
    hash_id = digest_root(args.root.resolve())
    text = ("// Generated from Vulkan shader/pipeline ABI sources.\n"
            "#pragma once\n"
            "#define LAS_VK_CACHE_PERSISTENT 1\n"
            f'#define LAS_VK_CACHE_BUILD_ID "{hash_id}"\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_text() != text:
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        temp.write_text(text)
        temp.replace(args.output)

if __name__ == "__main__":
    main()
