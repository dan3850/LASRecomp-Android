#!/usr/bin/env python3
"""Extend the five proven Castlevania shaders with ONE captured failing shader.

All copyrighted Maxwell/SPIR-V bytes remain local to the phone.
Refuse missing/ambiguous captures and never replace a working pack on failure.
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

from castlevania_ryujinx_probe import prepare as prepare_jobs, read_corpus_bytes
from package_castlevania_ryujinx_runtime import package as make_pack
from ryujinx_spirv_bridge import prepare as bridge_prepare

KEY = re.compile(r"^[0-9a-f]{16}_4$")
PREFIX, FAILURE_PC, FAILURE_REG = "ace294a5", 651, 8


def index_captures(archives):
    """Index independently exported captures. Distinct files cannot share a key."""
    items = {}
    for path in archives:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = Path(info.filename).name
                if not KEY.fullmatch(name.removesuffix(".snxs")) or not name.endswith(".snxs"):
                    continue
                if info.file_size > 1100000:
                    raise ValueError(f"excessive shader size in {path}: {name}")
                raw = archive.read(info)
                stage, code = read_corpus_bytes(raw)
                if stage != 4:
                    continue
                key = name[:-5]
                if key in items:
                    # SNXS metadata can legitimately differ across captures of
                    # the same Maxwell shader. Runtime matching uses code only.
                    if read_corpus_bytes(items[key])[1] != code:
                        raise ValueError("different Maxwell code under the same key: " + key)
                    continue
                items[key] = raw
    return items


def failure_candidate(captures, prefix=PREFIX):
    """Find the specific Maxwell shader safely; diagnose stale ZIP exports.

    The runtime shader key and SNXS file key may differ in the lower 32 bits,
    but shader_corpus_save writes h ^ mix with a 32-bit mix, so their upper
    32-bit prefix agrees for this pinned ScarletNX version.
    """
    matching, prefix_hits, opcode_hits = [], [], []
    for key, raw in sorted(captures.items()):
        if not key.endswith("_4"):
            continue
        _, code = read_corpus_bytes(raw)
        if len(code) < 8 * (FAILURE_PC + 1):
            if key.startswith(prefix):
                prefix_hits.append((key, "shader too short for PC " + str(FAILURE_PC)))
            continue
        word = struct.unpack_from("<Q", code, FAILURE_PC * 8)[0]
        is_tex = ((word >> 48) & 0xffc0) == 0xde80
        handle_register = (word >> 20) & 255
        if is_tex and handle_register == FAILURE_REG:
            opcode_hits.append(key)
        if key.startswith(prefix):
            prefix_hits.append((key, "TEX.B=" + str(is_tex) +
                                ", R=" + str(handle_register) +
                                ", word=" + f"{word:016x}"))
            if is_tex and handle_register == FAILURE_REG:
                matching.append(key)
    if len(matching) == 1:
        print("SEXTO SHADER CONFIRMADO:", matching[0],
              "(TEX.B PC", FAILURE_PC, "R", FAILURE_REG, ")", flush=True)
        return matching[0]

    found = len(captures)
    example = ", ".join(sorted(captures)[:8]) or "(nenhum)"
    if not prefix_hits:
        hint = ("O shader ace294a5 NAO esta presente nos ZIPs. "
                "Provavelmente foi usado o ZIP antigo. "
                "No aplicativo Castlevania, toque em 'Exportar shaders de fragmento (.zip)' "
                "e salve o NOVO ZIP em Download; depois execute este mesmo script.")
        if opcode_hits:
            hint += " Outros arquivos com TEX.B PC651 R8: " + ", ".join(opcode_hits[:8])
    else:
        hint = ("Existe chave com prefixo ace294a5, mas o codigo nao bate com "
                "o TEX.B PC651 R8 do log. Nao vamos trocar shaders incorretos. "
                "Detalhes: " + "; ".join(k + " [" + why + "]" for k, why in prefix_hits))
    raise ValueError(
        f"sexto shader: {len(matching)} correspondencias exatas; "
        f"{found} shaders de fragmento disponiveis. "
        f"Primeiras chaves: {example}. {hint}")


def run(archives, bridge_dir, nxnative, out_dir, pack_output):
    bridge_dir, nxnative, out_dir = map(Path, (bridge_dir, nxnative, out_dir))
    pack_output = Path(pack_output)
    current = json.loads((bridge_dir / "bridge-manifest.json").read_text())
    old = current.get("shaders", [])
    if len(old) != 5:
        raise ValueError("baseline must be the previous FIVE validated shaders")
    original = [x["key"] for x in old]
    if len(set(original)) != 5 or any(not KEY.fullmatch(k) for k in original):
        raise ValueError("invalid baseline shader keys")
    print("===== ARQUIVOS DE CAPTURA RECEBIDOS =====", flush=True)
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            names = [Path(info.filename).name for info in z.infolist()
                     if info.filename.lower().endswith(".snxs")]
            print(f"{archive}: {len(names)} arquivos SNXS", flush=True)
            if names:
                print("  Primeiro:", ", ".join(sorted(names)[:10]), flush=True)
    captures = index_captures(archives)
    print("Capturas unicas de fragmento:", len(captures), flush=True)
    if any(k not in captures for k in original):
        missing = [k for k in original if k not in captures]
        raise ValueError("missing original captured shaders: " + ", ".join(missing))
    sixth = failure_candidate(captures)
    if sixth in original:
        raise ValueError("the sixth shader is already present in baseline")
    chosen = sorted(original + [sixth])
    out_dir.mkdir(parents=True, exist_ok=True)
    inputzip = out_dir / "Castlevania-shaders-6-private.zip"
    with zipfile.ZipFile(inputzip, "w", compression=zipfile.ZIP_DEFLATED) as dest:
        for key in chosen:
            dest.writestr("shaders/" + key + ".snxs", captures[key])

    jobsdir = out_dir / "jobs"
    jobs, errors = prepare_jobs(inputzip, jobsdir)
    if errors or len(jobs) != 6:
        raise ValueError("shader capture validation failed: " + ", ".join(errors))
    project = nxnative / "dm/gfx/tools/dmsh_xlate/dmsh_xlate.csproj"
    if not project.is_file():
        raise ValueError("Ryujinx .NET translator checkout missing: " + str(project))
    if not shutil.which("dotnet") or not shutil.which("spirv-val"):
        raise ValueError("dotnet SDK and spirv-val are required; previous Termux scripts install both")
    dest = jobsdir / "spirv"
    dest.mkdir(exist_ok=True)
    for key in chosen:
        for suffix in (".spv", ".res.json"):
            (dest / (key + suffix)).unlink(missing_ok=True)
    command = ["dotnet", "run", "--project", str(project), "--configuration", "Release", "--",
               str(jobsdir / "jobs.json"), str(dest)]
    print("Translating six exact shaders with Ryujinx (using .NET cache)...", flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise ValueError("Ryujinx translator failed (native pack and APK unchanged)")
    for key in chosen:
        if not (dest / (key + ".spv")).is_file() or not (dest / (key + ".res.json")).is_file():
            raise ValueError("missing Ryujinx translation output for " + key)

    translatedzip = out_dir / "Castlevania-Ryujinx-Resultado-6-private.zip"
    with zipfile.ZipFile(translatedzip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for key in chosen:
            for suffix in (".spv", ".res.json"):
                name = key + suffix
                z.write(dest / name, arcname=name)
    adapted = out_dir / "bridge"
    manifest = bridge_prepare(translatedzip, adapted)
    if len(manifest["shaders"]) != 6:
        raise ValueError("shader bridge did not generate exactly six entries")
    for entry in manifest["shaders"]:
        spv = adapted / entry["file"]
        print("Validating Vulkan 1.3:", entry["key"], flush=True)
        subprocess.run(["spirv-val", "--target-env", "vulkan1.3", str(spv)], check=True)

    # Write to a separate temporary filename; never replace previous 5-shader
    # pack unless all six pass translation, bridge checks, and Vulkan validation.
    pack_output.parent.mkdir(parents=True, exist_ok=True)
    pending = pack_output.with_name(pack_output.name + ".partial")
    try:
        reports = make_pack(inputzip, adapted, pending)
        if len(reports) != 6:
            raise ValueError("invalid private pack count")
        pending.replace(pack_output)
    finally:
        pending.unlink(missing_ok=True)
    print("SUCCESS: six validated shaders, including new " + sixth, flush=True)
    print("PRIVATE PACK:", pack_output, flush=True)
    print("Existing 5-shader pack and APK were not overwritten.", flush=True)
    return sixth


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archives", nargs="+", type=Path,
                    help="all available Castlevania-shaders-SNXS export ZIPs")
    ap.add_argument("--baseline", type=Path,
                    default=Path.home() / "castlevania-ryujinx-bridge")
    ap.add_argument("--nxnative", type=Path,
                    default=Path.home() / ".cache/lasrecomp-ryujinx-probe/nxnative")
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "castlevania-ryujinx-six")
    ap.add_argument("--pack", type=Path,
                    default=Path("/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-Ryujinx-Ponte-6.snxrbr"))
    args = ap.parse_args()
    try:
        run(args.archives, args.baseline, args.nxnative, args.out, args.pack)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
