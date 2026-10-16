#!/usr/bin/env python3
"""Apply theboy181's v1.0.0 Stable 60fps v2 to PRIVATE recompiled game code.

Only two instructions become NOPs. Original NSOs, generated C, objects and
liblasgame.so stay untouched. No APK/runtime/renderer rebuild is needed.
"""
import argparse
import bisect
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess

from gen import Module, PATCHES, RANDO_CODE
from lifter import Insn
from nso import Nso

BUILD_ID = "ae16f71e002af8cb059a9a74c4d90f34ba984892"
BASE = 0x7000000000
# pchtxt offsets are relative to the memory image. offset_shift 0x100
# accounts for the NSO header in IPS files; it MUST NOT shift these PCs.
OFFSETS = (0x01019608, 0x01019628)
NOP = 0xd503201f  # little-endian bytes: 1F2003D5
MENU_CAPABILITY = "stable60-v2:" + BUILD_ID.upper() + ":01019608,01019628"
FLAGS = ("-std=gnu11", "-O1", "-g0", "-fPIC", "-fno-strict-aliasing",
         "-fvisibility=hidden", "-Wno-unused-label", "-Wno-return-type",
         '-DGAMELIB_ID="dev"')


def matching_nso(path):
    """Read only the header when locating the player's compatible main NSO."""
    try:
        if not path.is_file():
            return False
        with path.open("rb") as f:
            header = f.read(0x60)
        return (len(header) == 0x60 and header[:4] == b"NSO0" and
                header[0x40:0x60] == bytes.fromhex(BUILD_ID).ljust(32, b"\0"))
    except OSError:
        return False


def find_nso(workspace, roots=None):
    """Find a matching NSO without extracting, copying or changing game data."""
    for path in (workspace / "extracted/exefs/main", workspace / "exefs/main"):
        if matching_nso(path):
            return path.resolve()
    if roots is None:
        shared = Path(os.environ.get("EXTERNAL_STORAGE") or "/storage/emulated/0")
        prefix = Path(os.environ.get("PREFIX") or "/data/data/com.termux/files/usr")
        roots = [workspace, Path.home(), shared / "Download",
                 prefix / "var/lib/proot-distro/installed-rootfs", shared]
    skip = {".git", ".cache", ".gradle", ".npm", ".cargo", ".rustup",
            "node_modules", "objects", "gamecode", "android-sdk", "ndk",
            "Android", "proc", "sys", "dev", "usr"}
    preferred = {"extracted", "exefs", "input", "download", "downloads",
                 "games", "jogos", "switch", "root", "home"}
    visited = set()
    for root in roots:
        try:
            root = root.expanduser().resolve()
            if not root.is_dir() or root in visited:
                continue
            print(f"Procurando main v1.0.0 em: {root}", flush=True)
            for folder, dirs, files in os.walk(root, followlinks=False, onerror=lambda _: None):
                current = Path(folder)
                if current in visited:
                    dirs[:] = []
                    continue
                visited.add(current)
                dirs[:] = sorted((d for d in dirs if d not in skip), key=lambda d:
                    (d.lower() not in preferred and "lasrecomp" not in d.lower(), d.lower()))
                for name in ("main", "main.nso"):
                    if name in files:
                        candidate = current / name
                        if matching_nso(candidate):
                            return candidate.resolve()
        except OSError:
            continue
    return None


def lz4_block(data, size):
    """Bounded raw LZ4 decoder; avoids installing generator dependencies."""
    if not 0 <= size <= 128 * 1024 * 1024:
        raise ValueError("segmento NSO grande demais")
    out = bytearray()
    at = 0

    def length(n):
        nonlocal at
        if n == 15:
            while True:
                if at >= len(data):
                    raise ValueError("comprimento LZ4 truncado")
                extra = data[at]
                at += 1
                n += extra
                if extra != 255:
                    break
        return n

    while at < len(data):
        token = data[at]
        at += 1
        n = length(token >> 4)
        if at + n > len(data) or len(out) + n > size:
            raise ValueError("literais LZ4 fora do segmento")
        out.extend(data[at:at + n])
        at += n
        if at == len(data):
            break
        if at + 2 > len(data):
            raise ValueError("offset LZ4 truncado")
        distance = int.from_bytes(data[at:at + 2], "little")
        at += 2
        n = length(token & 15) + 4
        if not distance or distance > len(out) or len(out) + n > size:
            raise ValueError("copia LZ4 fora do segmento")
        # Copy chunks already produced, including overlapping repetitions.
        while n:
            count = min(n, distance)
            out.extend(out[len(out) - distance:len(out) - distance + count])
            n -= count
    if len(out) != size:
        raise ValueError("tamanho descomprimido NSO incorreto")
    return bytes(out)


def read_nso(path):
    raw = path.read_bytes()
    if len(raw) < 0x100 or raw[:4] != b"NSO0":
        raise ValueError("main nao e um NSO completo")
    if raw[0x40:0x60] != bytes.fromhex(BUILD_ID).ljust(32, b"\0"):
        raise ValueError("Build ID diferente do mod v1.0.0: nada foi aplicado")
    flags, = struct.unpack_from("<I", raw, 0xc)
    for i in range(3):
        file_off, mem_off, size = struct.unpack_from("<III", raw, 0x10 + i * 16)
        compressed, = struct.unpack_from("<I", raw, 0x60 + i * 4)
        stored = compressed if flags & (1 << i) else size
        if file_off < 0x100 or file_off + stored > len(raw) or mem_off + size > 128 * 1024 * 1024:
            raise ValueError("limites dos segmentos NSO invalidos")
    bss, = struct.unpack_from("<I", raw, 0x3c)
    if bss > 128 * 1024 * 1024:
        raise ValueError("BSS NSO invalida")
    return Nso(path, decompress=lz4_block)


def plan_sources(workspace, nso_path, menu_compatible=False):
    """Validate both sites and reproduce original C BEFORE preparing any output."""
    nso = read_nso(nso_path)
    folder = workspace / "build/gamecode/main"
    table = (folder / "main_table.c").read_text()
    array = re.search(r"const uint64_t main_fn_addrs\[\]\s*=\s*\{(.*?)\};", table, re.S)
    if not array:
        raise ValueError("tabela original de funcoes main ausente")
    starts = [int(v, 16) for v in re.findall(r"0x([0-9a-fA-F]+)ull", array[1])]
    if not starts or starts != sorted(set(starts)):
        raise ValueError("tabela de funcoes main invalida")
    entries = {}
    for offset in OFFSETS:
        pc = BASE + offset
        index = bisect.bisect_right(starts, pc) - 1
        end = starts[index + 1] if index + 1 < len(starts) else BASE + sum(nso.text)
        if index < 0 or not BASE + nso.text[0] <= pc < BASE + sum(nso.text) or pc >= end:
            raise ValueError(f"instrucao {offset:#x} fora do codigo original")
        if pc in PATCHES or offset in RANDO_CODE:
            raise ValueError(f"conflito com outro patch em {offset:#x}")
        entries.setdefault(starts[index], end)

    found = {}
    for path in sorted(folder.glob("main_[0-9][0-9][0-9].c")):
        text = path.read_text()
        for entry, end in entries.items():
            definition = re.search(rf"^void f_{entry:x}\(Cpu \*c\) \{{\n.*?^\}}", text, re.M | re.S)
            if not definition:
                continue
            if entry in found:
                raise ValueError(f"funcao f_{entry:x} duplicada")
            simd = "c" if '#include "simd.h"' in text else "asm"
            module = Module("main", None, BASE, simd, nso=nso)
            labels, _, tables = module.scan(entry, end)
            original = "\n".join(module.emit_function(entry, end, labels, tables, {}))
            if original != definition[0]:
                raise ValueError(f"{path.name}: C nao corresponde ao NSO/gerador; original preservado")
            for offset in OFFSETS:
                pc = BASE + offset
                if entry <= pc < end:
                    # A NOP changes neither registers (including LR) nor flags.
                    if menu_compatible:
                        module.runtime_nops.add(pc)
                    else:
                        module.cache[pc] = Insn("op", f"; /* Stable 60fps v2: main+{offset:#x} -> NOP */")
            patched = "\n".join(module.emit_function(entry, end, labels, tables, {}))
            found[entry] = (path, text, definition.start(), definition.end(), patched)
    if set(found) != set(entries):
        raise ValueError("faltam as funcoes originais do mod em build/gamecode/main")
    changes = {}
    for path, text, start, end, patched in found.values():
        changes.setdefault(path, (text, []))[1].append((start, end, patched))
    result = {}
    for path, (text, edits) in changes.items():
        for start, end, patched in sorted(edits, reverse=True):
            text = text[:start] + patched + text[end:]
        result[path] = text
    words = {f"{offset:08X}": f"{struct.unpack_from('<I', nso.image, offset)[0]:08X}"
             for offset in OFFSETS}
    return result, words


def write_changed(path, data):
    data = data.encode() if isinstance(data, str) else data
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(data)
    temporary.replace(path)


def check_object(path):
    with path.open("rb") as f:
        header = f.read(64)
    if len(header) < 64 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", header, 16) != (1, 183):
        raise ValueError(f"objeto nao e ELF Android ARM64: {path}")


def build(workspace, changes, output, menu_compatible=False):
    """Reuse complete private objects; compile ONLY changed chunks and a mod tag."""
    if platform.machine() != "aarch64" or os.environ.get("PREFIX") != "/data/data/com.termux/files/usr":
        raise ValueError("compile no Termux ARM64, fora do proot")
    if not shutil.which("clang"):
        raise ValueError("ferramenta ausente: clang")
    nm = shutil.which("llvm-nm") or shutil.which("nm")
    if not nm:
        raise ValueError("ferramenta ausente: llvm-nm/nm")
    source_root = workspace / "build/gamecode"
    private = workspace / "build/private-android-lasgame-termux"
    original_lib = private / "liblasgame.so"
    if not original_lib.is_file():
        raise ValueError(f"biblioteca original ausente: {original_lib}")
    sources = sorted(path for name in ("main", "sdk") for path in (source_root / name).glob("*.c"))
    sources.append(workspace / "tools/gamelib_entry.c")
    for name in ("main", "sdk"):
        if source_root / name / f"{name}_table.c" not in sources:
            raise ValueError(f"codigo original do modulo {name} incompleto")
    headers = [workspace / "runtime" / name for name in ("cpu.h", "simd.h", "gamelib.h")]
    newest_header = max(path.stat().st_mtime_ns for path in headers)
    objects = []
    for source in sources:
        rel = source.relative_to(source_root) if source.is_relative_to(source_root) else Path(source.name)
        obj = private / "objects" / rel.with_suffix(".o")
        if not obj.is_file() or obj.stat().st_mtime_ns < max(source.stat().st_mtime_ns, newest_header):
            raise ValueError(f"objeto original ausente/desatualizado: {rel}; conclua a compilacao incremental original")
        check_object(obj)
        objects.append((source, rel, obj))
    if original_lib.stat().st_mtime_ns < max(obj.stat().st_mtime_ns for _, _, obj in objects):
        raise ValueError("objetos mais novos que a biblioteca original; conclua o link original antes do mod")

    # Everything above is read-only. Each patched source/object is kept separately.
    flags = [*FLAGS, "-I" + str(workspace / "runtime")]
    stamp = output / "flags.json"
    write_changed(stamp, json.dumps(flags))
    replacements = {}
    tag = output / "sources/stable60_tag.c"
    tag_code = ('__attribute__((visibility("default")))\n'
                f'const char *lasgame_mod_stable60_v2(void) {{ return "{BUILD_ID}"; }}\n')
    if menu_compatible:
        tag_code += ('__attribute__((visibility("default")))\n'
                     f'const char *lasgame_mod_menu_v1(void) {{ return "{MENU_CAPABILITY}"; }}\n')
    write_changed(tag, tag_code)
    compile_sources = [(path, output / "sources" / path.relative_to(source_root)) for path in changes]
    for original, patched in compile_sources:
        write_changed(patched, changes[original])
    compile_sources.append((None, tag))
    for original, source in compile_sources:
        obj = output / "objects" / source.relative_to(output / "sources").with_suffix(".o")
        obj.parent.mkdir(parents=True, exist_ok=True)
        if not obj.exists() or obj.stat().st_mtime_ns < max(source.stat().st_mtime_ns, newest_header, stamp.stat().st_mtime_ns):
            temporary = obj.with_suffix(".o.partial")
            print(f"Compilando apenas o mod: {source.name}", flush=True)
            subprocess.run(["clang", *flags, "-c", str(source), "-o", str(temporary)], check=True)
            temporary.replace(obj)
        replacements[original] = obj
    linked = [replacements.get(source, obj) for source, _, obj in objects]
    linked.append(replacements[None])
    library = output / "liblasgame.so"
    temporary = library.with_suffix(".so.partial")
    subprocess.run(["clang", "-shared", "-Wl,-z,max-page-size=16384", "-Wl,-soname,liblasgame.so",
                    "-Wl,--build-id=sha1", "-o", str(temporary), *map(str, linked),
                    "-llog", "-landroid", "-ldl", "-lm"], check=True)

    def symbols(path, option):
        lines = subprocess.check_output([nm, "-D", option, str(path)], text=True)
        return {line.split()[-1] for line in lines.splitlines() if line.split()}

    exported = symbols(temporary, "--defined-only")
    if not {"lasgame_tables", "lasgame_mod_stable60_v2"} <= exported:
        raise ValueError("biblioteca do mod sem as tabelas/marcador esperados")
    if menu_compatible and "lasgame_mod_menu_v1" not in exported:
        raise ValueError("biblioteca sem identificador de compatibilidade com o menu")
    added = symbols(temporary, "--undefined-only") - symbols(original_lib, "--undefined-only")
    if menu_compatible:
        added -= {"rt_mod_nop"}  # the new APK exports this exact, supported hook
    if added:
        raise ValueError("o mod introduziu dependencias novas: " + ", ".join(sorted(added)))
    temporary.replace(library)
    return library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.home() / "lasrecomp-android-gen")
    parser.add_argument("--nso", type=Path, help="main NSO original da versao 1.0.0")
    parser.add_argument("--output", type=Path, help="diretorio separado para os arquivos privados do mod")
    parser.add_argument("--copy-to", type=Path)
    parser.add_argument("--menu-compatible", action="store_true",
                        help="mantem o original e os dois NOPs selecionaveis pelo novo menu Mods do APK")
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    nso = args.nso or find_nso(workspace)
    if nso is None:
        parser.error("main v1.0.0 nao encontrado nas pastas acessiveis do Termux. "
                     "Indique --nso com o arquivo main da pasta exefs do seu jogo; nada foi alterado")
    print(f"MAIN LOCALIZADO: {nso}", flush=True)
    variant = "stable60-menu" if args.menu_compatible else "stable60-v2"
    output = args.output or workspace / "build/private-android-lasgame-termux" / variant
    output = output.expanduser().resolve()
    reserved = [workspace / "build/gamecode", workspace / "build/private-android-lasgame-termux/objects",
                workspace / "runtime", workspace / "tools", nso.expanduser().resolve(),
                workspace / "build/private-android-lasgame-termux/liblasgame.so"]
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in reserved):
        parser.error("--output deve ser uma pasta separada dos originais")
    destination = (args.copy_to or Path("/storage/emulated/0/Download/LASRecomp") /
                   ("Mods-menu" if args.menu_compatible else "Stable60-v2") / "liblasgame.so").expanduser().resolve()
    if destination.name != "liblasgame.so":
        parser.error("--copy-to deve terminar em liblasgame.so, o nome aceito pelo importador do app")
    if destination.is_relative_to(workspace) and not destination.is_relative_to(output):
        parser.error("--copy-to deve ficar fora dos originais, ou dentro de --output")
    if destination == nso.expanduser().resolve():
        parser.error("--copy-to nao pode substituir o NSO original")
    try:
        changes, words = plan_sources(workspace, nso.expanduser().resolve(), args.menu_compatible)
        print(f"Build ID v1.0.0 confirmado: {BUILD_ID.upper()}", flush=True)
        for offset, word in words.items():
            selected = "original/NOP selecionaveis pelo menu" if args.menu_compatible else "D503201F (NOP)"
            print(f"main+0x{offset}: {word} -> {selected}", flush=True)
        library = build(workspace, changes, output, args.menu_compatible)
        write_changed(destination, library.read_bytes())
        write_changed(output / "mod.json", json.dumps({
            "mod": "theboy181 Stable 60fps v2", "nso_build_id": BUILD_ID,
            "menu_compatible": args.menu_compatible,
            "original_words": words, "patched_chunks": [p.name for p in changes],
            "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        }, indent=2) + "\n")
        print(f"\nBIBLIOTECA COM MOD: {destination}\n"
              "No aplicativo, importe esse .so pela opcao de codigo do jogo e reinicie.\n"
              "A biblioteca original foi preservada. O FPS real ainda precisa ser testado no celular.")
        if args.menu_compatible:
            print("Modo menu: o mod comeca DESATIVADO. Use o APK atualizado e importe/ative o .pchtxt em MODS.")
    except (OSError, ValueError, AssertionError, IndexError, struct.error,
            subprocess.CalledProcessError, ModuleNotFoundError) as error:
        parser.exit(1, f"ERRO: {error}\nNenhum NSO, C, objeto ou liblasgame.so original foi substituido.\n")


if __name__ == "__main__":
    main()
