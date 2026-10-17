#!/usr/bin/env python3
"""Persistent catalog across processes: concurrency, corruption and invalidation."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="las-replay-test-") as tmp:
    out = Path(tmp)
    exe = out / "catalog-test"
    header = out / "vulkan_cache_build_id.h"
    subprocess.run(["python3", "tools/vulkan-cache-build-id.py", "--output", str(header)], cwd=ROOT, check=True)
    stamp = header.stat().st_mtime_ns
    subprocess.run(["python3", "tools/vulkan-cache-build-id.py", "--output", str(header)], cwd=ROOT, check=True)
    assert header.stat().st_mtime_ns == stamp
    flags = os.environ.get("REPLAY_TEST_CFLAGS", "").split()
    subprocess.run([os.environ.get("CC", "gcc"), "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    *flags, "-I" + str(out), "tests/replay_cache_test.c", "runtime/nvn/vulkan/replay.c", "-lpthread", "-o", str(exe)], cwd=ROOT, check=True)
    seed = out / "seed"
    seed.mkdir()
    def run(mode, cwd):
        subprocess.run([str(exe), mode], cwd=cwd, check=True, timeout=30)
    run("seed", seed)
    recipes = list(seed.glob("cache/startup-v1/*/*.recipe"))
    assert len(recipes) == 2
    snapshots = {p.relative_to(seed): p.read_bytes() for p in recipes}
    for mode in ["load", "race", "failure", "driver", "code", "gpu", "features", "uuid", "disabled"]:
        folder = out / mode
        shutil.copytree(seed, folder)
        run(mode, folder)
        for path, data in snapshots.items():
            if mode not in {"load", "failure"}:
                assert (folder / path).read_bytes() == data
    for mutation in ["truncate", "checksum", "version", "oversized"]:
        folder = out / mutation
        shutil.copytree(seed, folder)
        path = folder / next(iter(snapshots))
        data = bytearray(path.read_bytes())
        if mutation == "truncate":
            data = data[:13]
        elif mutation == "checksum":
            data[-1] ^= 128
        elif mutation == "version":
            data[4:8] = (0x12345678).to_bytes(4, "little")
        else:
            # ReplayIdentity occupies 168 bytes, after the 16-byte prefix.
            data[16 + 168 + 8:16 + 168 + 12] = (0xffffffff).to_bytes(4, "little")
        path.write_bytes(data)
        run("corrupt", folder)
    assert not list(seed.rglob("*.tmp"))
    unavailable = out / "unavailable"
    (unavailable / "cache").mkdir(parents=True)
    (unavailable / "cache/startup-v1").write_text("must remain intact")
    run("unavailable", unavailable)
    assert (unavailable / "cache/startup-v1").read_text() == "must remain intact"
print("pipeline replay catalog: all checks PASS")
