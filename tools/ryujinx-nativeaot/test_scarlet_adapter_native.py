#!/usr/bin/env python3
"""Bit-for-bit test of the ACTUAL NativeAOT live Vulkan shader adapter.

No game shader hashes or SPIR-V blobs are built into the repo.
For every local Maxwell capture, call two native exports:
  - snx_ryu_translate_v1: pristine translated SPIR-V
  - snx_ryu_translate_scarlet_v1: automatically adapted for ScarletNX
Then independently derive the expected result using our audited Python
SPIR-V descriptor adapter (ryujinx_spirv_bridge.py) and compare all bytes.
The GPU path may only be enabled after this passes on the user's Android.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from castlevania_ryujinx_probe import read_corpus_bytes
from ryujinx_spirv_bridge import transform as offline_transform
from test_native import Result, make_job, validate_library, invoke

class ScarletMeta(C.Structure):
    _fields_ = [
        ("version", C.c_uint32),
        ("stage", C.c_uint32),
        ("cbuf_mask", C.c_uint32),
        ("input_mask", C.c_uint32),
        ("output_mask", C.c_uint32),
        ("texture_count", C.c_uint32),
        ("texture_info", C.c_uint32 * (64 * 4)),
    ]


def adapted_translate(native, source):
    if not hasattr(native, "snx_ryu_translate_scarlet_v1"):
        raise ValueError("Old Ryujinx .so does not have the dynamic Vulkan adapter. Download new NativeAOT artifact.")
    translator = native.snx_ryu_translate_scarlet_v1
    translator.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p,
                           C.c_size_t, C.POINTER(Result), C.POINTER(ScarletMeta)]
    translator.restype = C.c_int
    job = json.dumps(make_job("ps"), separators=(",", ":")).encode("utf-8")
    code = C.create_string_buffer(source)
    desc = C.create_string_buffer(job)
    result = Result()
    metadata = ScarletMeta()
    try:
        rc = translator(code, len(source), desc, len(job), C.byref(result), C.byref(metadata))
        if rc:
            error = (C.string_at(result.error, result.error_bytes).decode("utf-8", "replace")
                     if result.error else "(no error string)")
            raise RuntimeError(f"Scarlet native adapter failed rc={rc}: {error}")
        if metadata.version != 1 or metadata.stage != 4 or metadata.output_mask == 0:
            raise ValueError("Invalid adapted fragment shader metadata ABI")
        if metadata.texture_count > 64 or not result.spirv or not result.reflection:
            raise ValueError("Invalid native shader or texture count")
        shader = C.string_at(result.spirv, result.spirv_bytes)
        reflection = json.loads(C.string_at(result.reflection, result.reflection_bytes))
        return shader, reflection, metadata
    finally:
        native.snx_ryu_free_v1(C.byref(result))


def check_corpus(native, captures, output):
    success = 0
    errors = []
    for archive in captures:
        with zipfile.ZipFile(archive) as z:
            for name in sorted(z.namelist()):
                if not re.fullmatch(r"[0-9a-fA-F]{16}_4[.]snxs", Path(name).name):
                    continue
                stage, code = read_corpus_bytes(z.read(name))
                if stage != 4:
                    raise ValueError("Non-fragment capture unexpectedly selected")
                try:
                    original, ref_original = invoke(native, code)
                    adapted, ref_adapted, meta = adapted_translate(native, code)
                    if ref_original != ref_adapted:
                        raise ValueError("Ryujinx reflection diverged between ABI implementations")
                    expected, stats = offline_transform(original, ref_original)
                    if adapted != expected:
                        raise ValueError(
                            "NATIVE SCARLET ADAPTER DOES NOT MATCH INDEPENDENT PYTHON BRIDGE: "
                            f"{len(adapted)} vs {len(expected)} bytes")
                    if len(ref_adapted["textures"]) != meta.texture_count:
                        raise ValueError("Texture count mismatch between ABI metadata and reflection")
                    mask = sum(1 << int(cb["slot"]) for cb in ref_adapted["cbufs"])
                    if meta.cbuf_mask != mask:
                        raise ValueError("Constant buffer mask mismatch")
                    for i, tx in enumerate(ref_adapted["textures"]):
                        t = meta.texture_info[4*i:4*i+4]
                        handle = int(tx["handle"])
                        cb = int(tx["cbuf_slot"])
                        expected_source = [cb & 0xffff, handle & 0x3fff,
                                           (cb >> 16) - 1, (handle >> 14) & 0x3fff]
                        if list(t) != expected_source:
                            raise ValueError(f"Texture {i} handle source mismatch")
                    target = output / (Path(name).stem + ".scarlet.spv")
                    target.write_bytes(adapted)
                    validator = shutil.which("spirv-val")
                    if validator:
                        subprocess.run([validator, "--target-env", "vulkan1.3",
                                        str(target)], check=True)
                    success += 1
                    print(f"SCARLET_NATIVE_ADAPTER_OK: {Path(name).name}: "
                          f"{len(adapted)} SPIR-V bytes, {meta.texture_count} dynamic textures, "
                          f"{len(ref_adapted['cbufs'])} CBUFs, "
                          f"rewrite matches Python byte-for-byte", flush=True)
                except (ValueError, RuntimeError, subprocess.CalledProcessError) as e:
                    errors.append(f"{name}: {e}")
                    print(f"SCARLET_NATIVE_ADAPTER_FAIL: {name}: {e}", flush=True)
    if success + len(errors) == 0:
        raise ValueError("No Maxwell fragment captures for smoke test")
    print(f"SCARLET_NATIVE_ADAPTER_RESULT: {success}/{success+len(errors)} passed, "
          f"{len(errors)} failed")
    if errors:
        raise ValueError("; ".join(errors))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("library", type=Path)
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    try:
        a.out.mkdir(parents=True, exist_ok=True)
        check_corpus(validate_library(a.library), a.archives, a.out)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as e:
        ap.error(str(e))

if __name__ == "__main__":
    main()
