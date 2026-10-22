#!/usr/bin/env python3
"""Experimental OFFLINE Ryujinx SPIR-V -> ScarletNX descriptor bridge.

Reads the user's existing Ryujinx result ZIP; never embeds game shader binaries
in Git, changes ScarletNX runtime, or installs SPIR-V into an APK. The output
is NOT ready for Vulkan execution until runtime descriptor wiring is audited.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile

SPV_MAGIC = 0x07230203
FS_SET, FS_TEX_START, FS_TEX_MAX, FS_CBUF_MAX = 1, 34, 64, 18
OP_NAME, OP_EXTENSION, OP_CAPABILITY = 5, 10, 17
OP_TYPE_FLOAT, OP_CONSTANT, OP_VARIABLE = 22, 43, 59
OP_LOAD, OP_ACCESS_CHAIN, OP_INBOUNDS_ACCESS_CHAIN = 61, 65, 66
OP_COPY_OBJECT, OP_DECORATE, OP_ENTRYPOINT = 83, 71, 15
DEC_BINDING, DEC_SET = 33, 34
KEY = re.compile(r"^[0-9a-f]{16}_4$")


class BridgeError(ValueError):
    pass


def parse(blob):
    if len(blob) < 20 or len(blob) % 4:
        raise BridgeError("invalid SPIR-V length")
    w = list(struct.unpack(f"<{len(blob)//4}I", blob))
    if w[0] != SPV_MAGIC or w[1] != 0x00010300:
        raise BridgeError("expected SPIR-V 1.3")
    result, at = [], 5
    while at < len(w):
        n, op = w[at] >> 16, w[at] & 0xffff
        if not n or at + n > len(w):
            raise BridgeError("malformed SPIR-V instruction")
        result.append((op, w[at + 1:at + n]))
        at += n
    return w[:5], result


def encode(header, instructions):
    words = list(header)
    for op, operands in instructions:
        words.extend([((len(operands) + 1) << 16) | op, *operands])
    return struct.pack(f"<{len(words)}I", *words)


def str_operand(operands):
    return struct.pack(f"<{len(operands)}I", *operands).split(b"\0")[0].decode("utf8")


def binding_map(reflection):
    if reflection.get("stage") != "ps" or reflection.get("images") or reflection.get("sbufs"):
        raise BridgeError("only fragment textures and uniform buffers supported")
    out = {0: ("support", None)}
    for c in reflection["cbufs"]:
        b, slot = c["binding"], c["slot"]
        if b in out or not 0 <= slot < FS_CBUF_MAX:
            raise BridgeError("invalid cbuf binding")
        out[b] = ("cbuf", slot)
    for i, tex in enumerate(reflection["textures"]):
        if (i >= FS_TEX_MAX or tex["binding"] in out or tex["type"] != 3
                or tex["format"] != "Unknown" or tex["array"] != 1
                or tex["cbuf_slot"] != 0x30002 or (tex["handle"] >> 28) != 1
                or tex.get("separate") or tex.get("flags") not in (0, 2)):
            raise BridgeError("texture facts require another adapter")
        out[tex["binding"]] = ("texture", FS_TEX_START + i)
    return out


def transform(blob, reflection):
    header, inst = parse(blob)
    names, deco, consts, float_types, vars_by_id = {}, {}, {}, set(), {}
    for op, a in inst:
        if op == OP_NAME:
            names[a[0]] = str_operand(a[1:])
        elif op == OP_DECORATE and len(a) >= 3 and a[1] in (DEC_BINDING, DEC_SET):
            deco.setdefault(a[0], {})[a[1]] = a[2]
        elif op == OP_CONSTANT and len(a) == 3:
            consts[a[1]] = (a[0], a[2])
        elif op == OP_TYPE_FLOAT and len(a) == 2 and a[1] == 32:
            float_types.add(a[0])
        elif op == OP_VARIABLE:
            vars_by_id[a[1]] = a

    supports = [i for i, name in names.items() if name == "support_buffer"]
    if len(supports) != 1:
        raise BridgeError("expected one support_buffer")
    support = supports[0]
    if support not in vars_by_id or vars_by_id[support][2] != 2:
        raise BridgeError("unexpected support_buffer storage class")
    ones = sorted((t, i) for i, (t, v) in consts.items()
                  if t in float_types and v == 0x3f800000)
    if not ones:
        raise BridgeError("missing float32 constant 1.0")
    one_type, one_id = ones[0]

    bindings = binding_map(reflection)
    seen = {}
    for var, decorations in deco.items():
        if DEC_SET not in decorations or DEC_BINDING not in decorations:
            raise BridgeError("incomplete descriptor decorations")
        if decorations[DEC_SET] != 0:
            raise BridgeError("expected original descriptor set 0")
        b = decorations[DEC_BINDING]
        if b not in bindings or b in seen:
            raise BridgeError("reflection and SPIR-V descriptor mismatch")
        seen[b] = var
    if set(seen) != set(bindings) or seen[0] != support:
        raise BridgeError("reflection and SPIR-V resource sets differ")

    chains, loads = {}, set()
    for op, a in inst:
        if op in (OP_ACCESS_CHAIN, OP_INBOUNDS_ACCESS_CHAIN) and len(a) >= 4 and a[2] == support:
            if consts.get(a[3], (None, None))[1] != 5:
                raise BridgeError("support_buffer reads field other than render_scale")
            chains[a[1]] = a
        elif op == OP_LOAD and len(a) >= 3 and a[2] in chains:
            if len(a) != 3 or a[0] != one_type:
                raise BridgeError("unexpected support_buffer load type")
            loads.add(a[2])
    if not chains or set(chains) != loads:
        raise BridgeError("non-plain support_buffer pointer usage")

    # Fail closed on unusual uses; numerical equality in a constant literal,
    # decoration binding or GLSL.std.450 opcode does not refer to an SSA ID.
    for op, a in inst:
        if op == OP_ENTRYPOINT and support in a:
            raise BridgeError("support_buffer is an entrypoint interface variable")
        if op in (OP_NAME, OP_DECORATE, OP_VARIABLE) and a[0 if op != OP_VARIABLE else 1] == support:
            continue
        if op in (OP_ACCESS_CHAIN, OP_INBOUNDS_ACCESS_CHAIN) and len(a) >= 4 and a[2] == support:
            continue
        if op == OP_LOAD and len(a) >= 3 and a[2] in chains:
            continue
        if op in (OP_CONSTANT, OP_DECORATE, 12):
            continue
        if support in a or any(pointer in a for pointer in chains):
            raise BridgeError("unrecognized use of support_buffer")

    result, changes, removed = [], {}, 0
    for op, a in inst:
        if op in (OP_NAME, OP_DECORATE) and a and a[0] == support:
            removed += 1
            continue
        if op == OP_VARIABLE and a[1] == support:
            removed += 1
            continue
        if op in (OP_ACCESS_CHAIN, OP_INBOUNDS_ACCESS_CHAIN) and len(a) >= 4 and a[2] == support:
            removed += 1
            continue
        if op == OP_LOAD and len(a) >= 3 and a[2] in chains:
            result.append((OP_COPY_OBJECT, [one_type, a[1], one_id]))
            continue
        if op == OP_CAPABILITY and a == [10]:
            if any(q == OP_TYPE_FLOAT and x[1] == 64 for q, x in inst if len(x) >= 2):
                raise BridgeError("Float64 actually used")
            removed += 1
            continue
        if op == OP_CAPABILITY and a == [5378]:
            if any(5364 <= q <= 5369 for q, _ in inst):
                raise BridgeError("fragment interlock opcodes present")
            removed += 1
            continue
        if op == OP_EXTENSION and str_operand(a) == "SPV_EXT_fragment_shader_interlock":
            removed += 1
            continue
        if op == OP_DECORATE and len(a) >= 3 and a[0] in deco and a[1] in (DEC_SET, DEC_BINDING):
            old = deco[a[0]][DEC_BINDING]
            kind, target = bindings[old]
            if kind == "support":
                raise BridgeError("support_buffer decoration remains")
            result.append((op, [a[0], a[1], FS_SET if a[1] == DEC_SET else target]))
            changes[old] = {"kind": kind, "from_binding": old, "set": FS_SET, "binding": target}
            continue
        result.append((op, a))

    target = encode(header, result)
    _, checked = parse(target)
    rewritten = {}
    for op, a in checked:
        if op == OP_DECORATE and len(a) >= 3 and a[1] in (DEC_BINDING, DEC_SET):
            rewritten.setdefault(a[0], {})[a[1]] = a[2]
    expected = {(FS_SET, binding) for kind, binding in bindings.values() if kind != "support"}
    actual = {(v[DEC_SET], v[DEC_BINDING]) for v in rewritten.values()
              if DEC_BINDING in v and DEC_SET in v}
    if actual != expected:
        raise BridgeError("recheck of descriptor map failed")
    return target, {"textures": len(reflection["textures"]),
                    "cbuffers": len(reflection["cbufs"]),
                    "support_scale_replacements": len(loads),
                    "removed_instructions": removed,
                    "descriptor_map": sorted(changes.values(), key=lambda d: d["from_binding"])}


def prepare(zip_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        for name in sorted(n for n in names if n.endswith(".spv")):
            key = Path(name).stem
            if not KEY.fullmatch(key) or key + ".res.json" not in names:
                raise BridgeError("unexpected shader filename or missing reflection")
            source = archive.read(name)
            if len(source) > 4 * 1024 * 1024:
                raise BridgeError("oversize shader")
            ref = json.loads(archive.read(key + ".res.json"))
            if ref.get("key") != key:
                raise BridgeError("reflection key mismatch")
            patched, stats = transform(source, ref)
            file = key + ".bridge.spv"
            (output / file).write_bytes(patched)
            textures = [
                {"target_binding": FS_TEX_START + i,
                 "texture_cbuf": t["cbuf_slot"] & 0xffff,
                 "sampler_cbuf": (t["cbuf_slot"] >> 16) - 1,
                 "texture_word_offset": t["handle"] & 0x3fff,
                 "sampler_word_offset": (t["handle"] >> 14) & 0x3fff,
                 "usage_flags": t["flags"]}
                for i, t in enumerate(ref["textures"])]
            results.append({"key": key, "file": file,
                            "original_sha256": hashlib.sha256(source).hexdigest(),
                            "bridge_sha256": hashlib.sha256(patched).hexdigest(),
                            **stats, "texture_sources": textures,
                            "constant_buffers": ref["cbufs"]})
    if not results:
        raise BridgeError("no SPIR-V files found")
    report = {"status": "OFFLINE_ONLY_DO_NOT_LOAD", "resolution_scale": 1.0,
              "requirements_before_runtime": ["exact shader identity and validation",
                "native descriptor binding from CB2 TIC/TSC and CB stage state",
                "fragment I/O, UBO size and format matching", "spirv-val and on-device test"],
              "shaders": results}
    (output / "bridge-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ryujinx_zip")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        manifest = prepare(a.ryujinx_zip, a.out)
    except (BridgeError, ValueError, OSError, zipfile.BadZipFile) as e:
        ap.error(str(e))
    print("ScarletNX SPIR-V bridge (offline):", len(manifest["shaders"]), "shaders")
    for x in manifest["shaders"]:
        print(x["key"], x["textures"], "textures,", x["cbuffers"], "CBs,",
              x["support_scale_replacements"], "render-scale loads simplified")
    validator = shutil.which("spirv-val")
    if validator:
        for x in manifest["shaders"]:
            if subprocess.run([validator, "--target-env", "vulkan1.3",
                               str(Path(a.out) / x["file"])], check=False).returncode:
                print("Vulkan validation failed:", x["key"], file=sys.stderr)
                return 2
        print(f"spirv-val: all {len(manifest['shaders'])} passed (Vulkan 1.3)")
    else:
        print("spirv-val unavailable; validation not yet complete")
    print("DO NOT INJECT these modules into ScarletNX until runtime adapter is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
