#!/usr/bin/env python3
"""On-device smoke test of the NATIVE Ryujinx translator, no ScarletNX patch.

Uses every actual shader in the user's SNXS ZIP (not a hardcoded allowlist).
The real Ryujinx C# translator executes inside an ARM64 Bionic .so through
ctypes; its output and reflection are checked and freed through the C ABI.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from castlevania_ryujinx_probe import read_corpus_bytes


class Result(C.Structure):
    _fields_ = [
        ("spirv", C.c_void_p), ("spirv_bytes", C.c_size_t),
        ("reflection", C.c_void_p), ("reflection_bytes", C.c_size_t),
        ("error", C.c_void_p), ("error_bytes", C.c_size_t),
    ]


def validate_library(library: Path):
    native = C.CDLL(str(library.resolve()))
    native.snx_ryu_api_version.argtypes = []
    native.snx_ryu_api_version.restype = C.c_int
    native.snx_ryu_translate_v1.argtypes = [
        C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.POINTER(Result)]
    native.snx_ryu_translate_v1.restype = C.c_int
    native.snx_ryu_free_v1.argtypes = [C.POINTER(Result)]
    native.snx_ryu_free_v1.restype = None
    version = native.snx_ryu_api_version()
    if version != 1:
        raise ValueError(f"unsupported native translator ABI {version}")
    # A NULL input is rejected, without crossing the .NET exception boundary.
    empty = Result()
    if native.snx_ryu_translate_v1(None, 0, None, 0, C.byref(empty)) != -1:
        raise ValueError("native translator rejected-input contract broken")
    native.snx_ryu_free_v1(C.byref(empty))
    return native


def invoke(native, code: bytes, stage="ps"):
    # IGpuAccessor default answers are deliberately explicit: these resources
    # are NOT suitable for immediate Vulkan binding. Runtime state adaptation
    # (actual texture formats, CB1, render targets) is a separate phase.
    job = {
        "stage": stage, "tex": {}, "img": {}, "attr": {}, "fout": {},
        "local": [1, 1, 1],
    }
    encoded = json.dumps(job, separators=(",", ":")).encode()
    src = C.create_string_buffer(code)
    desc = C.create_string_buffer(encoded)
    result = Result()
    try:
        rc = native.snx_ryu_translate_v1(src, len(code), desc, len(encoded), C.byref(result))
        if rc:
            error = C.string_at(result.error, result.error_bytes).decode("utf-8", "replace") if result.error else ""
            raise RuntimeError(f"Ryujinx native translation failed ({rc}): {error}")
        if not result.spirv or not result.reflection:
            raise ValueError("native translator returned empty pointers")
        spv = C.string_at(result.spirv, result.spirv_bytes)
        info = json.loads(C.string_at(result.reflection, result.reflection_bytes))
        if len(spv) < 20 or spv[:4] != b"\x03\x02\x23\x07":
            raise ValueError("not SPIR-V output")
        if info.get("abi") != 1 or info.get("stage") != stage:
            raise ValueError("C ABI reflection does not match shader stage")
        if not isinstance(info.get("textures"), list) or not isinstance(info.get("cbufs"), list):
            raise ValueError("missing Ryujinx shader reflection")
        return spv, info
    finally:
        native.snx_ryu_free_v1(C.byref(result))


def run(library: Path, archives, output: Path):
    native = validate_library(library)
    output.mkdir(parents=True, exist_ok=True)
    count, errors = 0, []
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            for entry in sorted(z.namelist()):
                key = Path(entry).name
                if not re.fullmatch(r"[0-9a-fA-F]{16}_4[.]snxs", key):
                    continue
                stage, code = read_corpus_bytes(z.read(entry))
                if stage != 4:
                    raise ValueError("unexpected stage for " + key)
                count += 1
                print(f"RYUJINX NATIVE: translating {key}, {len(code)} Maxwell bytes", flush=True)
                try:
                    spv, reflection = invoke(native, code)
                    (output / (key[:-5] + ".spv")).write_bytes(spv)
                    (output / (key[:-5] + ".res.json")).write_text(
                        json.dumps(reflection, indent=2) + "\n", encoding="utf-8")
                    validator = shutil.which("spirv-val")
                    if validator:
                        subprocess.run([validator, "--target-env", "vulkan1.3",
                                        str(output / (key[:-5] + ".spv"))], check=True)
                    print(f"  OK: {len(spv)} SPIR-V bytes, "
                          f"{len(reflection['textures'])} textures, "
                          f"{len(reflection['cbufs'])} constant buffers", flush=True)
                except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                    errors.append(f"{key}: {error}")
                    print("  FAILED:", error, flush=True)
    if not count:
        raise ValueError("no SNXS fragment captures found")
    print(f"\nRESULTADO: {count - len(errors)}/{count} shaders translated by NativeAOT; "
          f"{len(errors)} errors", flush=True)
    if errors:
        raise ValueError("; ".join(errors))
    print("Confirmed: actual Ryujinx C# code compiled into Android .so was called.")
    print("No private shader packs, APKs, AOT code or ScarletNX source changed.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("library", type=Path)
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        run(args.library, args.archives, args.out)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
