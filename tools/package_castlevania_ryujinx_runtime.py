#!/usr/bin/env python3
"""Create a private, opt-in ScarletNX Ryujinx runtime pack from local captures.

No game-derived SPIR-V, Maxwell code or keys are committed to the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

from castlevania_ryujinx_probe import read_corpus_bytes
from ryujinx_spirv_bridge import parse, BridgeError

KEY = re.compile(r"^[0-9a-f]{16}_4$")
MAGIC = b"SNXRB001"
HEADER = struct.Struct("<8sI")
ENTRY = struct.Struct("<16sIIIIII")  # key, code, spv, cbuf, inputs, outputs, textures
PAIR = struct.Struct("<II")


def _io_masks(spirv):
    _, instructions = parse(spirv)
    decorations, variables = {}, {}
    for op, operands in instructions:
        if op == 71 and len(operands) >= 3 and operands[1] == 30:
            decorations[operands[0]] = operands[2]
        if op == 59:
            variables[operands[1]] = operands[2]
    inputs = outputs = 0
    for var, loc in decorations.items():
        storage = variables.get(var)
        if storage not in (1, 3):
            continue
        if not 0 <= loc < (32 if storage == 1 else 8):
            raise BridgeError("fragment stage input or output location out of range")
        if storage == 1:
            inputs |= 1 << loc
        else:
            outputs |= 1 << loc
    return inputs, outputs


def package(source_zip, bridge_dir, destination):
    bridge_dir = Path(bridge_dir)
    manifest = json.loads((bridge_dir / "bridge-manifest.json").read_text())
    if manifest.get("status") != "OFFLINE_ONLY_DO_NOT_LOAD":
        raise BridgeError("unrecognized or changed bridge manifest")
    entries = manifest.get("shaders", [])
    if len(entries) != 5 or len({x.get("key") for x in entries}) != 5:
        raise BridgeError("expected the five captured shaders")
    packed = []
    with zipfile.ZipFile(source_zip) as src:
        names = src.namelist()
        for item in entries:
            key = item["key"]
            if not KEY.fullmatch(key):
                raise BridgeError("invalid fragment shader key")
            filename = "shaders/" + key + ".snxs"
            if filename not in names:
                raise BridgeError("capture is absent: " + key)
            stage, code = read_corpus_bytes(src.read(filename))
            if stage != 4 or not 88 <= len(code) <= 65536:
                raise BridgeError("invalid source shader")
            spv = (bridge_dir / item["file"]).read_bytes()
            if hashlib.sha256(spv).hexdigest() != item["bridge_sha256"]:
                raise BridgeError("bridge SPIR-V SHA-256 mismatch")
            if len(spv) > 1024 * 1024:
                raise BridgeError("oversized SPIR-V")
            _, ins = parse(spv)
            bindings = {}
            for op, a in ins:
                if op == 71 and len(a) >= 3 and a[1] in (33, 34):
                    bindings.setdefault(a[0], {})[a[1]] = a[2]
            actual = {(v[34], v[33]) for v in bindings.values()
                      if 33 in v and 34 in v}
            expected = {(x["set"], x["binding"]) for x in item["descriptor_map"]}
            if actual != expected or any(s != 1 for s, _ in actual):
                raise BridgeError("SPIR-V bindings do not match manifest")
            cbuf = item["constant_buffers"]
            mask = 0
            for entry in cbuf:
                slot = entry["slot"]
                if not 0 <= slot < 18:
                    raise BridgeError("invalid constant buffer index")
                mask |= 1 << slot
            textures = item["texture_sources"]
            if len(textures) != item["textures"] or len(textures) > 64:
                raise BridgeError("incorrect texture count")
            for i, t in enumerate(textures):
                if (t["target_binding"] != 34 + i
                        or t["texture_cbuf"] != 2
                        or t["sampler_cbuf"] != 2
                        or not 0 <= t["texture_word_offset"] < 16384
                        or not 0 <= t["sampler_word_offset"] < 16384
                        or t["usage_flags"] not in (0, 2)):
                    raise BridgeError("unexpected runtime texture source")
            im, om = _io_masks(spv)
            if not om or om & ~255:
                raise BridgeError("no valid fragment colour output")
            record = ENTRY.pack(key[:16].encode("ascii"), len(code), len(spv),
                                mask, im, om, len(textures))
            pairs = b"".join(PAIR.pack(t["texture_word_offset"],
                                       t["sampler_word_offset"]) for t in textures)
            packed.append(record + pairs + code + spv)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = HEADER.pack(MAGIC, len(packed)) + b"".join(packed)
    if len(payload) > 4 * 1024 * 1024:
        raise BridgeError("pack exceeds 4 MB")
    destination.write_bytes(payload)
    return [{"key": x["key"], "raw": x["maxwell_bytes"] if "maxwell_bytes" in x else "verified",
             "textures": x["textures"]} for x in entries]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("captures", help="local Castlevania-shaders-SNXS.zip")
    ap.add_argument("--bridge", default=str(Path.home() / "castlevania-ryujinx-bridge"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        entries = package(args.captures, args.bridge, args.out)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        ap.error(str(exc))
    print(f"Private Ryujinx pack: {len(entries)} shaders -> {args.out}")
    print("Not installed: import through the experimental Castlevania launcher.")


if __name__ == "__main__":
    main()
