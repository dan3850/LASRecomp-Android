#!/usr/bin/env python3
"""Real Vulkan GMEM and R8-atlas regression tests; no game files needed.

Needs clang/clang++, SDL3 headers, Vulkan headers/loader, VMA headers,
glslangValidator and spirv-val. A software Vulkan ICD (Lavapipe) is sufficient.
Extra include/library paths: VULKAN_TEST_CFLAGS and VULKAN_TEST_LDFLAGS.
Use VK_ICD_FILENAMES to select an ICD. Runtime test asserts remain enabled.
"""
import os
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def run(*cmd):
    subprocess.run([str(x) for x in cmd], check=True, cwd=ROOT)

with tempfile.TemporaryDirectory(prefix="las-vulkan-") as tmp:
    out = Path(tmp)
    run("python3", "tools/vulkan-cache-build-id.py", "--output", out / "vulkan_cache_build_id.h")
    cc = shlex.split(os.environ.get("CC", "clang"))
    cxx = shlex.split(os.environ.get("CXX", "clang++"))
    flags = ["-O1", "-g", "-ffunction-sections", "-fdata-sections", "-Wno-format",
             "-Wno-nullability-completeness", "-Iruntime", "-Iruntime/nvn", "-I" + str(out)]
    flags += shlex.split(os.environ.get("VULKAN_TEST_CFLAGS", ""))
    run(*cc, "-std=gnu11", *flags, "tests/gmem_plan_test.c", "-o", out / "plan-test")
    run(out / "plan-test")
    sources = ["tests/vulkan_gmem_test.c", "runtime/nvn/maxwell/translate.c",
               "runtime/nvn/vulkan/textures.c", "runtime/nvn/tegra.c", "runtime/nvn/formats.c",
               "runtime/nvn/bcn_decode.c", "runtime/nvn/astc.c", "runtime/nvn/vulkan/vma.cpp", "runtime/nvn/vulkan/replay.c"]
    real_shaders = os.environ.get("VULKAN_TEST_REAL_SHADERS") == "1"
    if real_shaders:
        flags.append("-DLAS_TEST_REAL_SHADERS")
        sources += ["runtime/nvn/vulkan/shaders.c", "runtime/nvn/smaa_data.c"]
        flags += ["-Ithird_party/smaa/Textures", "-I" + str(out)]
        smaa = (ROOT / "third_party/smaa/SMAA.hlsl").read_bytes().decode("latin-1").replace("\r", "")
        smaa = "".join(c if ord(c) < 128 else "?" for c in smaa)
        (out / "smaa_hlsl.inc").write_text("\n".join(json.dumps(s + "\n") for s in smaa.splitlines()))
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
    for src in sorted(p for p in out.iterdir() if p.suffix in {".comp", ".vert", ".frag"}):
        spv = Path(str(src) + ".spv") if src.suffix != ".comp" else src.with_suffix(".spv")
        run("glslangValidator", "-V", "--target-env", "vulkan1.3", src, "-o", spv)
        run("spirv-val", "--target-env", "vulkan1.3", spv)
    run(out / "gpu-test", out)
    if real_shaders:
        state = out / "persistent-state"
        state.mkdir()
        run(out / "gpu-test", "--replay-seed", state)
        run(out / "gpu-test", "--replay-load", state)
        spv = next((state / "cache/spirv").glob("*.spv"))
        damaged = bytearray(spv.read_bytes()); damaged[-1] ^= 128; spv.write_bytes(damaged)
        env = dict(os.environ, REPLAY_TEST_CORRUPT_SPIRV="1")
        subprocess.run([str(out / "gpu-test"), "--replay-load", str(state)], cwd=ROOT, env=env, check=True)
