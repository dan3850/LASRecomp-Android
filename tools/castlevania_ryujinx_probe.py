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
import zipfile

HEADER = struct.Struct("<4sIIIII")
STAGES = {0: "vs", 4: "ps", 5: "cs"}
MAX_SHADER = 1 << 20

# Five initial TEX.B failures in the Castlevania runtime log. The first
# 8 key digits agree with corpus filenames; the lower digits vary because
# the log and corpus use different mixes of runtime shader state.
KNOWN_FAILURES = {
    "642ea78b": (304, 22),
    "214b89d4": (651, 4),
    "7e305789": (648, 16),
    "41e4dbaf": (661, 12),
    "fc2b7c81": (720, 12),
}
NAME = re.compile(r"^[0-9a-fA-F]{16}_[0-5]$")


def read_corpus_bytes(raw):
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


def read_corpus(path):
    return read_corpus_bytes(Path(path).read_bytes())


def iter_captures(source):
    source = Path(source)
    if source.is_dir():
        inputs = sorted(source.rglob('*.snxs'))
        if not inputs:
            raise ValueError('no .snxs corpus files found')
        for path in inputs:
            yield path.name, path.read_bytes()
    elif source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            inputs = sorted((item for item in archive.infolist()
                             if not item.is_dir() and item.filename.lower().endswith('.snxs')),
                            key=lambda item: item.filename)
            if not inputs:
                raise ValueError('ZIP contains no .snxs files')
            if len(inputs) > 8192:
                raise ValueError('ZIP contains too many shaders')
            for info in inputs:
                if not 24 <= info.file_size <= MAX_SHADER + 16408:
                    yield Path(info.filename).name, b''
                    continue
                yield Path(info.filename).name, archive.read(info)
    elif source.is_file() and source.suffix.lower() == '.snxs':
        yield source.name, source.read_bytes()
    else:
        raise ValueError('pass a directory, .snxs file or exported .zip')


def prepare(corpus, output, stages=("ps",)):
    source = Path(corpus)
    dest = Path(output).resolve()
    if source.is_dir() and (dest == source.resolve() or source.resolve() in dest.parents):
        raise ValueError("output cannot be inside corpus directory")
    binary_dir = dest / "maxwell"
    binary_dir.mkdir(parents=True, exist_ok=True)
    jobs, errors, report, seen = [], [], [], set()
    for filename, raw in iter_captures(source):
        try:
            stage, code = read_corpus_bytes(raw)
            name = Path(filename).stem
            if not NAME.fullmatch(name) or not name.endswith("_" + str(stage)):
                raise ValueError("expected filename <16hex>_<stage>.snxs")
            name = name.lower()
            if STAGES[stage] not in stages:
                continue
            if name in seen:
                raise ValueError("duplicate shader name")
            seen.add(name)
            target = binary_dir / (name + ".bin")
            target.write_bytes(code)
            jobs.append({"key": name, "stage": STAGES[stage],
                         "code": str(target), "tex": {}, "img": {},
                         "attr": {}, "fout": {}, "local": [1, 1, 1]})
            item = {"key": name, "stage": STAGES[stage],
                    "maxwell_bytes": len(code), "words": len(code) // 8}
            failure = KNOWN_FAILURES.get(name[:8])
            if stage == 4 and failure:
                pc, expected_reg = failure
                if (pc + 1) * 8 <= len(code):
                    word = struct.unpack_from("<Q", code, pc * 8)[0]
                    # TEX.B encodes its texture-handle register in bits 20-27.
                    actual_reg = (word >> 20) & 255
                    is_tex_b = ((word >> 48) & 0xffc0) == 0xde80
                    item["known_failure"] = {
                        "pc": pc, "handle_register": actual_reg,
                        "expected_register": expected_reg,
                        "tex_b_opcode": is_tex_b,
                        "matches_log_position": is_tex_b and actual_reg == expected_reg,
                        "machine_word_hex": f"{word:016x}",
                    }
            report.append(item)
        except (OSError, ValueError, struct.error) as exc:
            errors.append(f"{filename}: {exc}")
    (dest / "jobs.json").write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")
    (dest / "errors.txt").write_text("\n".join(errors) + ("\n" if errors else ""), encoding="utf-8")
    (dest / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return jobs, errors

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", help="captured ScarletNX .zip, .snxs file or captures/shaders directory")
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
    print("Report:", Path(args.out).resolve() / "report.json")
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
    command = [dotnet, "run", "--project", str(project.resolve()), "--configuration", "Release", "--",
               str(output / "jobs.json"), str(output / "spirv")]
    print("Running Ryujinx translation in external process (no APK modifications)")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
