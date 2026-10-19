#!/usr/bin/env python3
"""Extract owned Switch XCI to exefs/ + romfs/ with the installed Yanu CLI.

The original Yanu (https://github.com/nozwock/yanu, GPL-2.0) supports XCI
via 'convert --kind nsp' followed by 'unpack --base'. This is a subprocess
orchestrator: no Yanu code, game assets, keys or binaries are bundled here.

Usage:
 python3 tools/extrair_mario_xci.py "/storage/emulated/0/SwitchRoms/Mario.xci"
 python3 tools/extrair_mario_xci.py ROM.xci --output /path/to/extracted
 python3 tools/extrair_mario_xci.py ROM.xci --base-nsp converted-name.nsp

The converted NSP is cached inside <output>/_yanu_converted/ so interrupted
extractions may be resumed without converting the XCI repeatedly.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
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


def choose_base(candidates: list[Path], requested: str | None) -> Path:
    if requested:
        name = Path(requested).name
        if Path(requested).name != requested or not name.lower().endswith(".nsp"):
            fail("--base-nsp deve conter somente o nome do NSP gerado (sem caminhos).")
        chosen = next((p for p in candidates if p.name == name), None)
        if chosen is None:
            fail(f"NSP '{name}' não encontrado na conversão. Disponíveis: "
                 + ", ".join(p.name for p in candidates))
        return chosen
    if not candidates:
        fail("Yanu não gerou NSP válido. Verifique os avisos do 4NXCI e suas chaves locais.")
    if len(candidates) > 1:
        fail("O XCI gerou vários NSPs; não é seguro escolher um automaticamente. "
             "Execute novamente com --base-nsp NOME.nsp. Arquivos: "
             + ", ".join(p.name for p in candidates))
    return candidates[0]


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
    yanu = shutil.which(args.yanu_cli)
    if not yanu:
        fail("yanu-cli não foi encontrado no PATH. Instale/configure seu Yanu "
             "existente; verifique com: yanu-cli --help")
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
    base = choose_base(nsps, args.base_nsp)
    print(f"== Extraindo ExeFS/RomFS com Yanu: {base.name} ==", flush=True)
    subprocess.run([yanu, "unpack", "--base", str(base),
                    "--outdir", str(dest)], check=True)
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
        print("NSP temporário selecionado excluído após extração verificada.")
    else:
        print("NSP intermediário preservado: " + str(base))
        print("Use --delete-intermediate numa nova extração, se preferir "
              "removê-lo após a validação.")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrai XCI pessoal em exefs/romfs/ usando o Yanu já instalado.")
    parser.add_argument("xci", help="Caminho do arquivo .xci da sua própria cópia")
    parser.add_argument("--output", help="Pasta de saída; padrão: NOME-extraido ao lado do XCI")
    parser.add_argument("--yanu-cli", default="yanu-cli", help="Comando do Yanu instalado")
    parser.add_argument("--base-nsp", help="Nome do NSP base quando um XCI gera vários NSPs")
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
