#!/usr/bin/env python3
"""Standalone generator fixture: python3 tests/test_vk_cache_identity.py"""
import importlib.util
from pathlib import Path
import tempfile

SOURCE = Path(__file__).resolve().parents[1] / "tools/vulkan-cache-build-id.py"
spec = importlib.util.spec_from_file_location("vk_cache_id", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def add(root, name, content):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    for name in module.TRACKED:
        add(root, name, "stable shader layout\n")
    add(root, "runtime/nvn/maxwell/shader.c", "shader translation ABI A\n")
    markers = [
        "// unrelated GMEM implementation before pipeline code\n",
        "// ================================================================== programs\n",
        "program ABI A\n",
        "// ================================================================== vertex formats / fixed function tables\n",
        "format ABI A\n",
        "// ================================================================== graphics pipelines\n",
        "graphics pipeline ABI A\n",
        "// ================================================================== feedback snapshots\n",
        "// unrelated render target optimization\n",
        "static VkResult build_compute_raw(\n",
        "compute pipeline ABI A\n",
        "static void build_compute(\n",
        "// unrelated scheduling\n",
        "static bool pipeline_recipe_state(\n",
        "replay recipe ABI A\n",
        "static struct CsEnt\n",
        "// unrelated portable GMEM streaming\n",
    ]
    add(root, "runtime/nvn/vulkan/exec.c", "".join(markers))
    base = module.digest_root(root)
    assert len(base) == 64
    add(root, "runtime/nvn/vulkan/exec.c",
        "".join(markers).replace("unrelated GMEM", "improved GMEM").replace(
            "unrelated portable", "optimized portable"))
    assert module.digest_root(root) == base, "GMEM-only changes must preserve replay cache"
    add(root, "compilar-lasrecomp-termux.sh", "new incremental build recipe")
    assert module.digest_root(root) == base, "build script edit must preserve replay cache"
    add(root, "runtime/nvn/maxwell/shader.c", "shader translation ABI B\n")
    new = module.digest_root(root)
    assert new != base, "shader translator change must invalidate"
    add(root, "runtime/nvn/maxwell/shader.c", "shader translation ABI A\n")
    altered = "".join(markers).replace("graphics pipeline ABI A", "graphics pipeline ABI B")
    add(root, "runtime/nvn/vulkan/exec.c", altered)
    assert module.digest_root(root) != base, "pipeline compiler change must invalidate"
    add(root, "runtime/nvn/vulkan/exec.c", "".join(markers))
    add(root, "runtime/nvn/vulkan/vk.h", "different descriptor layout\n")
    assert module.digest_root(root) != base, "Vulkan API changes must invalidate"
    print("PASS: performance-only changes reuse cache; shader and pipeline ABI changes invalidate")
