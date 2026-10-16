#!/usr/bin/env python3
"""Extract the private generated functions relevant to an existing Android crash.

Reads an existing diagnostic ZIP/log and the matching local, unstripped game
library. Does not compile, execute the game, change files, or upload anything.
The output contains user-generated game code and belongs outside the repository.
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

REPORT = re.compile(r"host pc ([0-9a-f]+) \((f_[0-9a-f]+)\+([0-9a-f]+)\)\s*"
                    r"host lr ([0-9a-f]+) \((f_[0-9a-f]+)(?:\+([0-9a-f]+))?\)")
DEFINITION = re.compile(r"^void (f_[0-9a-f]+)\(Cpu \*c\) \{\n.*?^\}", re.M | re.S)


def crash_functions(log, symbols):
    # Never attribute an older crash when the latest report is incomplete or
    # concerns a native function outside the generated game's tables.
    log = re.split(r"(?m)^\*\*\* ", log)[-1]
    matches = list(REPORT.finditer(log))
    if not matches:
        raise ValueError("Não há PC/LR de funções recompiladas nesse log.")
    pc, name, off, lr, caller, caller_off = matches[-1].groups()
    if caller_off is not None:
        return {name, caller}, "PC/LR com nomes independentes."
    if caller not in symbols:
        raise ValueError(f"A biblioteca não contém {caller}; use a biblioteca não stripada desse teste.")
    # Old reports overwrite PC's name while resolving LR; PC's numeric offset
    # survives. LR is somewhere inside the reported caller. Recover the bounded
    # interval of possible PC function starts in the ELF's address space.
    start, size = symbols[caller]
    po = int(off, 16)
    low = start - (int(lr, 16) - int(pc, 16)) - po
    candidates = {n for n, (a, s) in symbols.items() if low <= a < low + size and po < s}
    if not candidates:
        raise ValueError("Nenhum candidato compatível; confira se a biblioteca corresponde ao APK do log.")
    return candidates | {caller}, "Relatório antigo: candidatos limitados pelo PC, LR e tamanho do chamador; não são uma atribuição definitiva."


def extract(source, wanted):
    result = {}
    if not wanted:
        return result
    for path in sorted(source.rglob("*.c")):
        text = path.read_text(errors="replace")
        for match in DEFINITION.finditer(text):
            if match[1] in wanted:
                result[match[1]] = (path.relative_to(source), match[0])
        if wanted <= result.keys():
            break
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="ZIP de diagnóstico existente ou runtime-tail.txt")
    parser.add_argument("game_root", type=Path, nargs="?", default=Path.home() / "lasrecomp-android-gen")
    parser.add_argument("--library", type=Path)
    parser.add_argument("--nm", default=shutil.which("llvm-nm") or shutil.which("nm"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        library = args.library or args.game_root / "build/private-android-lasgame-termux/liblasgame.so"
        source = args.game_root / "build/gamecode"
        if not args.nm or not library.is_file() or not source.is_dir():
            raise ValueError("São necessários llvm-nm, liblasgame.so não stripada e build/gamecode nesse projeto.")
        if zipfile.is_zipfile(args.log):
            with zipfile.ZipFile(args.log) as z:
                names = [n for n in z.namelist() if n.endswith("runtime-tail.txt")]
                if len(names) != 1:
                    raise ValueError("ZIP sem um único runtime-tail.txt.")
                log = z.read(names[0]).decode(errors="replace")
        else:
            log = args.log.read_text(errors="replace")
        nm = subprocess.run([args.nm, "-S", "--defined-only", "-n", str(library)],
                            capture_output=True, text=True, check=True).stdout
        symbols = {n: (int(a, 16), int(s, 16)) for a, s, n in
                   re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[tT]\s+(f_[0-9a-f]+)$", nm, re.M)}
        wanted, reason = crash_functions(log, symbols)
        found = extract(source, wanted)
        # Include direct callees of the selected functions, once, to retain the
        # null-producing call's implementation without collecting the whole game.
        callees = {n for _, text in found.values() for n in re.findall(r"\b(f_[0-9a-f]+)\(c\)", text)}
        if len(callees - wanted) <= 32:
            found.update(extract(source, callees - wanted))
        if not wanted <= found.keys():
            raise ValueError("Fontes ausentes: " + ", ".join(sorted(wanted - found.keys())))
        report = [reason, "Biblioteca: " + str(library), "Funções selecionadas: " + ", ".join(sorted(wanted))]
        for name, (path, text) in sorted(found.items()):
            report.extend([f"\n=== {name} ({path}) ===", text])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(report) + "\n")
        print(f"Extraído sem recompilar ou executar o jogo: {args.output}")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
