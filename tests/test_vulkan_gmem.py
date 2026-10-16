#!/usr/bin/env python3
"""Real Vulkan GMEM and R8-atlas regression tests; no game files needed.

Needs clang/clang++, SDL3 headers, Vulkan headers/loader, VMA headers,
glslangValidator and spirv-val. A software Vulkan ICD (Lavapipe) is sufficient.
Extra include/library paths: VULKAN_TEST_CFLAGS and VULKAN_TEST_LDFLAGS.
Use VK_ICD_FILENAMES to select an ICD. Runtime test asserts remain enabled.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def run(*cmd):
    subprocess.run([str(x) for x in cmd], check=True, cwd=ROOT)

with tempfile.TemporaryDirectory(prefix="las-vulkan-") as tmp:
    out = Path(tmp)
    cc = shlex.split(os.environ.get("CC", "clang"))
    cxx = shlex.split(os.environ.get("CXX", "clang++"))
    flags = ["-O1", "-g", "-ffunction-sections", "-fdata-sections", "-Wno-format",
             "-Wno-nullability-completeness", "-Iruntime", "-Iruntime/nvn"]
    flags += shlex.split(os.environ.get("VULKAN_TEST_CFLAGS", ""))
    run(*cc, "-std=gnu11", *flags, "tests/gmem_plan_test.c", "-o", out / "plan-test")
    run(out / "plan-test")
    sources = ["tests/vulkan_gmem_test.c", "runtime/nvn/maxwell/translate.c",
               "runtime/nvn/vulkan/textures.c", "runtime/nvn/tegra.c", "runtime/nvn/formats.c",
               "runtime/nvn/bcn_decode.c", "runtime/nvn/astc.c", "runtime/nvn/vulkan/vma.cpp"]
    objects = []
    for i, src in enumerate(sources):
        obj = out / f"{i}.o"
        is_cxx = src.endswith(".cpp")
        run(*(cxx if is_cxx else cc), "-std=c++17" if is_cxx else "-std=gnu11",
            *flags, "-c", src, "-o", obj)
        objects.append(obj)
    libraries = shlex.split(os.environ.get("VULKAN_TEST_LDFLAGS", "-lvulkan"))
    run(*cxx, "-Wl,--gc-sections", *objects, *libraries, "-lpthread", "-lm", "-o", out / "gpu-test")
    run(out / "gpu-test", "--emit", out)
    for src in sorted(out.glob("*.comp")):
        spv = src.with_suffix(".spv")
        run("glslangValidator", "-V", "--target-env", "vulkan1.3", src, "-o", spv)
        run("spirv-val", "--target-env", "vulkan1.3", spv)
    run(out / "gpu-test", out)
