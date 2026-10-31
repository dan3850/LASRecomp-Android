#!/data/data/com.termux/files/usr/bin/bash
# Audit the 2026 ScarletNX runtime and Android packaging prerequisites.
# Read-only: does not modify the stable APK, game code or native libraries.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.cache/lasrecomp-scarletnx-upgrade"
DIR="$BASE/output/apk-libs/arm64-v8a"
[ -d "$DIR" ] || { echo "ERRO: bibliotecas experimentais ausentes: $DIR"; exit 1; }
command -v readelf >/dev/null || { echo "ERRO: readelf ausente"; exit 1; }
python3 - "$DIR" "$ROOT" <<'PY'
from pathlib import Path
import subprocess, sys, re
directory, root = map(Path, sys.argv[1:])
system = set("libc.so libm.so libdl.so liblog.so libandroid.so libz.so libvulkan.so libEGL.so libGLESv1_CM.so libGLESv2.so libGLESv3.so libOpenSLES.so libaaudio.so libmediandk.so libjnigraphics.so libstdc++.so".split())
required = ("libscarletnx.so","libLLVM.so","libc++_shared.so","libffi.so","libzstd.so.1","libxml2.so.16","libiconv.so")
missing = [n for n in required if not (directory/n).is_file()]
if missing: raise SystemExit("ERRO: faltam: "+", ".join(missing))
errors = []
for p in sorted(directory.iterdir()):
    if not p.is_file(): continue
    h = subprocess.check_output(["readelf","-h",str(p)],text=True)
    if "AArch64" not in h: errors.append(f"{p.name}: nao ARM64")
    d = subprocess.check_output(["readelf","-d",str(p)],text=True)
    names = re.findall(r"\(NEEDED\).*?\[([^]]+)\]",d)
    sonames = re.findall(r"\(SONAME\).*?\[([^]]+)\]",d)
    if sonames and sonames[0] != p.name: errors.append(f"{p.name}: SONAME {sonames[0]}")
    if "RPATH" in d or "RUNPATH" in d: errors.append(f"{p.name}: RPATH/RUNPATH presente")
    for name in names:
        if name not in system and not (directory/name).is_file():
            errors.append(f"{p.name}: dependencia ausente {name}")
    print(f"{p.name}: {len(names)} dependencias")
print("=== RESULTADO ===")
if errors:
    for e in errors: print("ERRO:",e)
    raise SystemExit(1)
print("ELF_DEPENDENCIES_OK")
print("AVISO: bibliotecas *.so.1 e *.so.16 nao sao automaticamente extraidas pelo empacotador Android.")
print("AVISO: libLLVM do Termux requer teste de carregamento real fora do Termux.")
print("AVISO: o empacotador existente requer modulo AOT SNX ABI 12 compativel.")
print("AVISO: o JNI atual do projeto contem sonda de Mario, nao inicializador Zelda 2026.")
print("APK_ZELDA_2026_READY=NO")
PY
