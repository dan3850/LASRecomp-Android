#!/usr/bin/env python3
"""Prepare a local ScarletNX SNXS shader corpus for nxnative's Ryujinx translator.

Never uploads shaders, game data, or dumps to GitHub. This is an OFFLINE
translation comparison, NOT a compatible ScarletNX SPIR-V cache.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

HEADER = struct.Struct("<4sIIIII")
STAGES = {0: "vs", 4: "ps", 5: "cs"}
MAX_SHADER = 1 << 20
NAME = re.compile(r"^[0-9a-fA-F]{16}_[0-5]$")


def read_corpus(path):
    raw = path.read_bytes()
    if len(raw) < HEADER.size:
        raise ValueError("truncated SNXS header")
    magic, version, info_size, stage, length, max_bytes = HEADER.unpack_from(raw)
    if magic != b"SNXS" or version != 1:
        raise ValueError("unsupported SNXS magic/version")
    if not (0 < info_size <= 16384):
        raise ValueError("invalid ShaderInfo size")
    if not (0 < length <= max_bytes <= MAX_SHADER):
        raise ValueError("invalid shader code length")
    if HEADER.size + info_size + length != len(raw):
        raise ValueError("truncated or trailing bytes")
    if stage not in STAGES:
        raise ValueError(f"stage {stage} is not supported by dmsh_xlate (vs/ps/cs only)")
    code = raw[HEADER.size + info_size:]
    if len(code) % 8:
        raise ValueError("Maxwell instructions not 8-byte aligned")
    if stage != 5 and length < 88:
        raise ValueError("graphics program has no full 80-byte SPH")
    return stage, code


def prepare(corpus, output, stages=("ps",)):
    source = Path(corpus)
    inputs = sorted(source.rglob("*.snxs")) if source.is_dir() else [source]
    if not inputs or any(not p.is_file() for p in inputs):
        raise ValueError("no .snxs corpus files found")
    dest = Path(output).resolve()
    if source.is_dir() and (dest == source.resolve() or source.resolve() in dest.parents):
        raise ValueError("output cannot be inside corpus directory")
    binary_dir = dest / "maxwell"
    binary_dir.mkdir(parents=True, exist_ok=True)
    jobs, errors = [], []
    for path in inputs:
        try:
            stage, code = read_corpus(path)
            name = path.stem
            if not NAME.fullmatch(name) or not name.endswith("_" + str(stage)):
                raise ValueError("expected filename <16hex>_<stage>.snxs")
            if STAGES[stage] not in stages:
                continue
            target = binary_dir / (name.lower() + ".bin")
            target.write_bytes(code)
            # Query facts (texture dimensionality, image formats, vertex/output
            # types and c1 jump tables) are NOT provided by the SNXS header.
            # Missing facts are deliberately left out; this is only a probe.
            jobs.append({"key": name.lower(), "stage": STAGES[stage],
                         "code": str(target), "tex": {}, "img": {},
                         "attr": {}, "fout": {}, "local": [1, 1, 1]})
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    (dest / "jobs.json").write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")
    (dest / "errors.txt").write_text("\n".join(errors) + ("\n" if errors else ""), encoding="utf-8")
    return jobs, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", help="directory containing ScarletNX captures/shaders/*.snxs")
    ap.add_argument("--out", required=True, help="local working directory for the Ryujinx jobs")
    ap.add_argument("--stage", choices=("ps", "vs", "cs", "all"), default="ps")
    ap.add_argument("--nxnative", type=Path, help="nxnative source root; enables running the C# translator")
    args = ap.parse_args(argv)
    stages = ("vs", "ps", "cs") if args.stage == "all" else (args.stage,)
    try:
        jobs, errors = prepare(args.corpus, args.out, stages)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(f"SNXS: {len(jobs)} translation jobs prepared, {len(errors)} rejected files")
    for problem in errors[:10]:
        print("SKIP:", problem, file=sys.stderr)
    print("Jobs:", Path(args.out).resolve() / "jobs.json")
    if not jobs:
        print("No compatible shaders found. Capture a new scene with 'Shader captures' ON.")
        return 2
    print("WARNING: test translation only. No texture fact table, c1 jump table or Vulkan")
    print("descriptor reconciliation. Generated SPIR-V must NOT be loaded by ScarletNX.")
    if not args.nxnative:
        print("Pass --nxnative /path/to/nxnative on a machine with .NET SDK 10 to translate.")
        return 0
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        print("ERROR: dotnet executable not found (requires .NET SDK 10).", file=sys.stderr)
        return 2
    project = args.nxnative / "dm/gfx/tools/dmsh_xlate/dmsh_xlate.csproj"
    if not project.is_file():
        print(f"ERROR: missing nxnative tool: {project}", file=sys.stderr)
        return 2
    output = Path(args.out).resolve()
    (output / "spirv").mkdir(parents=True, exist_ok=True)
    command = [dotnet, "run", "--project", str(project.resolve()), "--",
               str(output / "jobs.json"), str(output / "spirv")]
    print("Running Ryujinx translation in external process (no APK modifications)")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
