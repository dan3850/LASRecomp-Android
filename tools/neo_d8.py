#!/usr/bin/env python3
"""Provision an official, pinned Java D8 for the Neo controller build.

Kotlin 2.4 produces metadata not supported by older SDK-bundled D8/R8.
Google documents R8 >= 9.1.29 as required for Kotlin 2.4:
https://developer.android.com/build/kotlin-support

This downloads only the host-independent Java dexer, never a native binary.
The artifact is cached; native build objects and caches remain untouched.
"""
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
import zipfile


VERSION = "9.1.29"
URL = "https://storage.googleapis.com/r8-releases/raw/" + VERSION + "/r8.jar"
MAIN_CLASS = "com/android/tools/r8/D8.class"


def is_d8_jar(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as jar:
            return MAIN_CLASS in jar.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: neo_d8.py CACHE_DIRECTORY", file=sys.stderr)
        return 2
    cachedir = Path(sys.argv[1]).expanduser().resolve()
    dest = cachedir / ("r8-" + VERSION + ".jar")
    if is_d8_jar(dest):
        print(dest)
        return 0

    cachedir.mkdir(parents=True, exist_ok=True)
    print("Obtendo D8/R8 " + VERSION + " do repositório oficial (uma vez)", file=sys.stderr)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="r8-", suffix=".tmp", dir=cachedir, delete=False
        ) as temp:
            tmp_path = Path(temp.name)
            request = urllib.request.Request(URL, headers={
                "User-Agent": "LASRecomp-Android-Termux/1.0"
            })
            with urllib.request.urlopen(request, timeout=90) as response:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    temp.write(block)
        if not is_d8_jar(tmp_path):
            raise ValueError("JAR inválido: com.android.tools.r8.D8 ausente")
        os.replace(tmp_path, dest)
    except Exception as error:
        print("ERRO: download/validação de D8 " + VERSION + ": " + str(error),
              file=sys.stderr)
        print("Use LASRECOMP_D8_JAR=/caminho/r8.jar para indicar um D8 compatível.",
              file=sys.stderr)
        return 1
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
