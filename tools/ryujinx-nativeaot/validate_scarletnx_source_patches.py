#!/usr/bin/env python3
"""Validate experimental Zelda shader patches against actual pinned ScarletNX sources.

Never writes into the supplied ScarletNX checkout. This is source compatibility
validation, not a SPIR-V translation or Android build test.
"""
import argparse
import importlib.util
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = [
    ("SHFL predicate", "tools/patch_scarletnx_zelda_shfl_predicate.py",
     "src/nx/gpu/shader/spirv_translate.c"),
    ("Conditional EXIT", "tools/patch_scarletnx_zelda_conditional_exit.py",
     "src/nx/gpu/shader/spirv_translate.c"),
    ("128 KiB window", "tools/patch_scarletnx_zelda_shader_window.py",
     "src/nx/gpu/vk/pipeline.c"),
]

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def run(source):
    with tempfile.TemporaryDirectory(prefix="scarletnx-source-audit-") as tmp:
        scratch = Path(tmp)
        originals = {}
        for _, _, rel in SPECS:
            if rel not in originals:
                original = source / rel
                if not original.is_file():
                    raise RuntimeError(f"Missing ScarletNX source: {original}")
                destination = scratch / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                originals[rel] = original.read_bytes()

        modules = []
        for index, (name, module_path, rel) in enumerate(SPECS):
            mod = load_module(f"snx_audit_{index}", ROOT / module_path)
            before = (scratch / rel).read_bytes()
            mod.apply(scratch)
            after = (scratch / rel).read_bytes()
            if after == before:
                raise RuntimeError(f"{name}: no effective change")
            mod.apply(scratch)
            if (scratch / rel).read_bytes() != after:
                raise RuntimeError(f"{name}: second apply changed source")
            modules.append((name, mod))
            print(f"PASS apply/idempotence: {name}", flush=True)

        for name, mod in reversed(modules):
            mod.apply(scratch, revert=True)
            print(f"PASS revert: {name}", flush=True)

        for rel, original in originals.items():
            if (scratch / rel).read_bytes() != original:
                raise RuntimeError(f"Source differs after round-trip: {rel}")
        print("PASS: source round-trip byte-for-byte; original checkout untouched", flush=True)
        print("NOTE: no C compilation, SPIR-V validation, or graphical behavior checked", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scarletnx_checkout", type=Path)
    args = parser.parse_args()
    run(args.scarletnx_checkout.resolve())
