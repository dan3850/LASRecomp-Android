#!/usr/bin/env python3
"""Extract owned Switch XCI to exefs/ + romfs/ with the installed Yanu CLI.

The original Yanu (https://github.com/nozwock/yanu, GPL-2.0) supports XCI
via 'convert --kind nsp' followed by 'unpack --base [--update ...]'. This is a subprocess
orchestrator: no Yanu code, game assets, keys or binaries are bundled here.

Usage:
 python3 tools/extrair_mario_xci.py "/storage/emulated/0/SwitchRoms/Mario.xci"
 python3 tools/extrair_mario_xci.py ROM.xci --output /path/to/extracted
 python3 tools/extrair_mario_xci.py ROM.xci --base-nsp converted-name.nsp
 python3 tools/extrair_mario_xci.py ROM.xci --update-nsp "title[UPD][1.2.0].nsp"

The converted NSP is cached inside <output>/_yanu_converted/ so interrupted
extractions may be resumed without converting the XCI repeatedly.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> None:
    raise RuntimeError(message)


def has_game_data(root: Path) -> bool:
    exefs = root / "exefs"
    romfs = root / "romfs"
    return ((exefs / "main").is_file() and romfs.is_dir()
            and any(romfs.iterdir()))


def converted_nsps(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.nsp") if p.is_file() and p.stat().st_size > 0)


def choose_packages(
    candidates: list[Path], requested_base: str | None,
    requested_update: str | None,
) -> tuple[Path, Path | None]:
    """Select unambiguous base and its official [UPD] package.

    XCI/4NXCI may produce multiple unrelated games, patches or DLCs. Never
    guess a package based on size, ordering or title substring alone.
    """
    if not candidates:
        fail("Yanu não gerou NSP válido. Verifique o 4NXCI e suas chaves locais.")

    by_name = {p.name: p for p in candidates}

    def selected(option: str, flag: str) -> Path:
        if Path(option).name != option or not option.lower().endswith(".nsp"):
            fail(f"{flag} deve conter somente o nome do NSP convertido.")
        if option not in by_name:
            fail(f"{flag}={option!r} não encontrado. Disponíveis: "
                 + ", ".join(p.name for p in candidates))
        return by_name[option]

    def patch_base_name(path: Path) -> str | None:
        import re
        # Format produced by Yanu/4NXCI: GAME[UPD][1.2.0].nsp
        match = re.fullmatch(
            r"(.+)\[UPD\](?:\[[^\[\]]+\])?\.nsp", path.name, re.IGNORECASE
        )
        return match.group(1).casefold() if match else None

    updates = [p for p in candidates if patch_base_name(p) is not None]
    normal = [p for p in candidates if p not in updates]

    if requested_base:
        base = selected(requested_base, "--base-nsp")
        if base in updates:
            fail("O arquivo escolhido com --base-nsp é uma atualização [UPD].")
    elif len(normal) == 1:
        base = normal[0]
    else:
        fail("Não foi possível determinar um único NSP base. Utilize "
             "--base-nsp NOME.nsp. Arquivos: "
             + ", ".join(p.name for p in candidates))

    matching = [p for p in updates
                if patch_base_name(p) == base.stem.casefold()]

    if requested_update:
        update = selected(requested_update, "--update-nsp")
        if update not in updates or update not in matching:
            fail("--update-nsp deve identificar uma atualização [UPD] "
                 "correspondente ao NSP base escolhido.")
    elif len(matching) == 1:
        update = matching[0]
    elif len(matching) > 1:
        fail("Há várias atualizações do jogo base. Informe "
             "--update-nsp NOME.nsp: " + ", ".join(p.name for p in matching))
    else:
        update = None

    # Do not ignore any extra packages in the converted XCI. They may be
    # DLC, a different title, or an update for a different base game.
    unselected = [p for p in candidates if p != base and p != update]
    if unselected:
        if requested_base or requested_update:
            print("AVISO: NSPs extras ignorados por seleção explícita: "
                  + ", ".join(p.name for p in unselected), file=sys.stderr)
        else:
            fail("Existem outros NSPs não selecionados. Selecione os arquivos "
                 "explicitamente ou examine a conversão antes de prosseguir: "
                 + ", ".join(p.name for p in unselected))

    return base, update

def run(args: argparse.Namespace) -> Path:
    source = Path(args.xci).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".xci":
        fail(f"Informe um arquivo .xci existente, não .xc0/.xcz: {source}")
    dest = (Path(args.output).expanduser().resolve()
            if args.output else source.with_name(source.stem + "-extraido"))
    if dest == source or source in dest.parents:
        fail("A pasta de saída não pode ser o próprio arquivo XCI.")
    if dest == source.parent:
        fail("Escolha uma pasta de saída separada da pasta que contém o XCI.")
    if has_game_data(dest):
        print(f"Extração existente verificada; não vou refazer: {dest}")
        return dest
    if any(p.exists() for p in (dest / "exefs", dest / "romfs", dest / "basedata")):
        fail("Há uma extração parcial na saída; não vou sobrescrever nada: "
             + str(dest) + ". Examine os arquivos existentes.")
    # The official Termux bootstrap installs a 'yanu' wrapper inside
    # $PREFIX/bin and explicitly deprecates the old 'yanu-cli' command.
    # Prefer it, but retain backwards compatibility with older installs.
    names = ([args.yanu_cli] if args.yanu_cli != "auto"
             else ["yanu", "yanu-cli"])
    yanu = next((found for name in names if (found := shutil.which(name))), None)
    if not yanu:
        fail("Yanu não encontrado no PATH (procurei: " + ", ".join(names)
             + "). Confira com: command -v yanu; command -v yanu-cli. "
             "Se já extraiu Zelda com outro comando/proot, informe o caminho "
             "com --yanu-cli /caminho/do/executavel; nenhuma reinstalação "
             "ou download foi feito.")
    convdir = dest / "_yanu_converted"
    convdir.mkdir(parents=True, exist_ok=True)
    nsps = converted_nsps(convdir)
    if not nsps:
        free = shutil.disk_usage(convdir).free
        if free < source.stat().st_size * 2:
            print("AVISO: espaço livre pode ser insuficiente para conversão + "
                  "extração; os arquivos não serão removidos automaticamente.",
                  file=sys.stderr)
        print("== Convertendo XCI para NSP com o Yanu/4NXCI (uma vez) ==", flush=True)
        subprocess.run([yanu, "convert", "--kind", "nsp", str(source),
                        "--outdir", str(convdir)], check=True)
        nsps = converted_nsps(convdir)
    else:
        print("== Reaproveitando NSP já convertido; sem reconverter XCI ==", flush=True)
    base, update = choose_packages(nsps, args.base_nsp, args.update_nsp)
    print(f"== NSP base: {base.name} ==", flush=True)
    if update is not None:
        print(f"== Aplicando atualização: {update.name} ==", flush=True)

    # The upstream Termux 'yanu' wrapper forwards all arguments via
    # bash -c 'yanu '"$*" rather than safely quoting "$@".
    # Therefore an NSP filename with spaces is split into extra CLI
    # arguments inside proot ('unexpected argument Mario'). Work around
    # the installed wrapper without modifying/reinstalling it or copying
    # the multi-gigabyte NSP: create temporary symlinks with safe names.
    # The real source files remain untouched. If Yanu returns 0 despite
    # failing (the wrapper's EXIT trap can mask its status), the existing
    # exefs/main + romfs postcondition still catches the failure.
    if Path(yanu).name == "yanu":
        with tempfile.TemporaryDirectory(prefix=".yanu-args-", dir=convdir) as tmp:
            temp = Path(tmp)
            safe_base = temp / "base.nsp"
            safe_base.symlink_to(base.resolve())
            unpack_command = [yanu, "unpack", "--base", str(safe_base)]
            if update is not None:
                safe_update = temp / "update.nsp"
                safe_update.symlink_to(update.resolve())
                unpack_command.extend(["--update", str(safe_update)])
            unpack_command.extend(["--outdir", str(dest)])
            subprocess.run(unpack_command, check=True)
    else:
        unpack_command = [yanu, "unpack", "--base", str(base)]
        if update is not None:
            unpack_command.extend(["--update", str(update)])
        unpack_command.extend(["--outdir", str(dest)])
        subprocess.run(unpack_command, check=True)
    if not has_game_data(dest):
        fail("A extração terminou mas exefs/main e romfs não estão completos. "
             "Verifique a versão do Yanu, o log e as chaves da sua própria "
             "Switch; nada foi excluído: " + str(dest))
    print("\nEXTRAÇÃO CONCLUÍDA")
    print("Pasta: " + str(dest))
    print("ExeFS: " + str(dest / "exefs"))
    print("RomFS: " + str(dest / "romfs"))
    print("Execução encontrada: " + str(dest / "exefs" / "main"))
    if args.delete_intermediate:
        # Remove only the selected NSP produced/staged by this helper,
        # and only after verifying that both game data directories exist.
        base.unlink()
        if update is not None:
            update.unlink()
        print("NSPs intermediários utilizados excluídos após extração verificada.")
    else:
        print("NSP base preservado: " + str(base))
        if update is not None:
            print("NSP da atualização preservado: " + str(update))
        print("Use --delete-intermediate numa nova extração, se preferir "
              "removê-lo após a validação.")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrai XCI pessoal em exefs/romfs/ usando o Yanu já instalado.")
    parser.add_argument("xci", help="Caminho do arquivo .xci da sua própria cópia")
    parser.add_argument("--output", help="Pasta de saída; padrão: NOME-extraido ao lado do XCI")
    parser.add_argument("--yanu-cli", default="auto", help="Comando instalado; padrão: detecta yanu (Termux) ou yanu-cli")
    parser.add_argument("--base-nsp", help="Nome do NSP base, se seleção automática for ambígua")
    parser.add_argument("--update-nsp", help="Nome do NSP [UPD] desejado, se houver várias atualizações")
    parser.add_argument("--delete-intermediate", action="store_true",
                        help="Excluir apenas o NSP intermediário selecionado após extração válida")
    args = parser.parse_args()
    try:
        run(args)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
