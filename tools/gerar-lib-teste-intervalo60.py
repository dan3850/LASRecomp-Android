#!/data/data/com.termux/files/usr/bin/python3
"""Teste reversivel do Zelda: forca 1 vsync no setter, sem alterar os originais.

Gera uma liblasgame.so separada para importar no app. NAO corrige gargalos
reais: se 60 fps nao couberem no orcamento de 16,67 ms, pode dar camera lenta.
"""
import argparse
import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path

tools = Path(__file__).resolve().parent
helper_file = tools / "apply-stable60-mod.py"
spec = importlib.util.spec_from_file_location("apply_stable60", helper_file)
if spec is None or spec.loader is None:
    raise SystemExit("ERRO: apply-stable60-mod.py ausente")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def patch_setter(workspace, changes):
    path = workspace / "build/gamecode/main/main_001.c"
    if not path.is_file():
        raise ValueError(f"codigo privado nao encontrado: {path}")
    source = changes.get(path)
    if source is None:
        source = path.read_text(encoding="utf-8")
    pat = re.compile(r"^void f_7000017800\(Cpu \*c\) \{\n.*?^}", re.M | re.S)
    matches = list(pat.finditer(source))
    if len(matches) != 1:
        raise ValueError("f_7000017800 nao encontrada uma unica vez")
    fn = matches[0].group(0)
    original = (
        "c->x[11] = (uint32_t)(0x812cull);\n"
        "    c->x[9] = (uint32_t)((uint32_t)c->x[9] + 0x1ull);\n"
        "    { uint64_t ea = c->x[10] + c->x[11]; ST32(ea, (uint32_t)c->x[9]); }"
    )
    replacement = (
        "c->x[11] = (uint32_t)(0x812cull);\n"
        "    c->x[9] = (uint32_t)((uint32_t)c->x[9] + 0x1ull);\n"
        "    { uint64_t ea = c->x[10] + c->x[11]; ST32(ea, 1u); }"
        " /* teste isolado: somente o intervalo; registradores preservados */"
    )
    if fn.count(original) != 1:
        raise ValueError("o setter nao corresponde ao codigo enviado no TXT")
    patched_fn = fn.replace(original, replacement, 1)
    m = matches[0]
    changes[path] = source[:m.start()] + patched_fn + source[m.end():]
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.home() / "lasrecomp-android-gen")
    parser.add_argument("--nso", type=Path, help="NSO main v1.0.0 original do usuario")
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    output = workspace / "build/private-android-lasgame-termux/intervalo60-teste"
    destination = Path("/storage/emulated/0/Download/LASRecomp/Intervalo60-teste/liblasgame.so")
    try:
        nso = args.nso or helper.find_nso(workspace)
        if nso is None:
            raise ValueError("NSO main v1.0.0 nao localizado; informe --nso")
        nso = nso.expanduser().resolve()
        # Os dois NOPs do Stable60 permanecem separados e selecionaveis no MODS.
        changes, _ = helper.plan_sources(workspace, nso, menu_compatible=True)
        changed = patch_setter(workspace, changes)
        print("Patch de teste validado em:", changed, flush=True)
        print("Original: +0x812c = valor decidido pelo Zelda")
        print("Teste:    +0x812c = 1, independentemente da decisao")
        print("Compilando apenas os arquivos C privados afetados, sem clean...", flush=True)
        lib = helper.build(workspace, changes, output, menu_compatible=True)
        if not lib.is_file() or not lib.stat().st_size:
            raise ValueError("biblioteca experimental nao gerada")
        helper.write_changed(destination, lib.read_bytes())
        note = destination.parent / "LEIA-INTERVALO60-TESTE.txt"
        helper.write_changed(note, (
            "Teste reversivel de intervalo de 60 FPS.\n"
            "Importe esta liblasgame.so no aplicativo e reinicie o jogo.\n"
            "Na primeira comparacao, deixe Stable 60fps v2 DESLIGADO.\n"
            "Teste modo Diablo dentro e fora da casa.\n"
            "Se houver camera lenta, reimporte sua liblasgame.so anterior.\n"
            "Nao altera NSO, fontes privados, objetos, APK nem outro mod.\n"
        ))
        print("SHA256:", hashlib.sha256(destination.read_bytes()).hexdigest())
        print("\nBIBLIOTECA EXPERIMENTAL:", destination)
        print("Importe no app como codigo do jogo, reinicie e teste (Stable60 DESLIGADO).")
        print("Para desfazer: importe novamente a biblioteca anterior.")
    except (OSError, ValueError, AssertionError, IndexError,
            subprocess.CalledProcessError, ModuleNotFoundError) as e:
        parser.exit(1, f"ERRO: {e}\nNenhum original foi substituido.\n")


if __name__ == "__main__":
    main()
