#!/usr/bin/env python3
"""Read-only check of Zelda ScarletNX AOT build IDs for Stable 60fps v3.

The PCHTXT offsets address guest code in the original NSO; they are NOT
offsets into the already recompiled Android ELF. This utility never patches
game data, code, binaries, settings, or the APK.
"""
from __future__ import annotations

import argparse
import mmap
from pathlib import Path

ZELDA_ID = "01006BB00C6F0000"
V110 = "602492BC6DC3533DF6BC57E572520C96F89319EC"
V100 = "AE16F71E002AF8CB059A9A74C4D90F34BA984892"
SITES = (0x010196D8, 0x010196F8)
DEFAULT_AOT = Path("/storage/emulated/0/Download/ZeldaRecomp") / ZELDA_ID / (ZELDA_ID + "_code.so")


def check(path: Path) -> int:
    print("=== Zelda Stable 60fps v3: diagnostico somente leitura ===")
    print("Biblioteca:", path)
    if not path.is_file():
        print("ERRO: biblioteca nao encontrada (use --aot CAMINHO)")
        return 2
    print("Tamanho:", path.stat().st_size, "bytes")
    with path.open("rb") as file:
        if file.read(4) != b"\x7fELF":
            print("ERRO: nao parece uma biblioteca ELF")
            return 2
        file.seek(0)
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as blob:
            matches = {}
            for version, build in [("v1.1.0 / Stable 60fps v3", V110), ("v1.0.0 / Stable 60fps v2", V100)]:
                pattern = bytes.fromhex(build)
                found = []
                start = 0
                while len(found) < 5:
                    at = blob.find(pattern, start)
                    if at < 0:
                        break
                    found.append(at)
                    start = at + 1
                matches[version] = found
                print(f"Build ID {version}: {'ENCONTRADO' if found else 'NAO ENCONTRADO'}")
                for at in found:
                    print("  Ocorrencia no ELF em 0x%X (dado, nao endereco do patch)" % at)
    print("PCHTXT v1.1.0: offset_shift=0x100, locais efetivos:")
    for offset in SITES:
        print("  main+0x%08X (NOP ARM64 = D503201F)" % offset)
    print("Esses nao sao offsets para modificar a biblioteca .so recompilada.")
    if matches["v1.1.0 / Stable 60fps v3"]:
        print("RESULTADO: ID do mod v1.1.0 presente no AOT; confirmar que pertence ao main.")
        return 0
    if matches["v1.0.0 / Stable 60fps v2"]:
        print("RESULTADO: ID v1.0.0 encontrado, mas nao o v1.1.0. NAO aplicar o mod v3.")
        return 1
    print("RESULTADO: os IDs nao apareceram como bytes contiguos. Inconclusivo; NAO aplicar o mod.")
    return 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aot", type=Path, default=DEFAULT_AOT)
    args = p.parse_args()
    return check(args.aot)


if __name__ == "__main__":
    raise SystemExit(main())
