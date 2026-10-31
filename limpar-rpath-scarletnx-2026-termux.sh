#!/data/data/com.termux/files/usr/bin/bash
# Remove build-time search paths from isolated ScarletNX 2026 APK staging copies.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DIR="$HOME/.cache/lasrecomp-scarletnx-upgrade/output/apk-libs/arm64-v8a"
[ -d "$DIR" ] || { echo "ERRO: staging nao encontrado"; exit 1; }
command -v patchelf >/dev/null || { echo "ERRO: instale patchelf no Termux"; exit 1; }
for lib in "$DIR"/*.so*; do
  [ -f "$lib" ] || continue
  case "$lib" in "$PREFIX"/*) echo "ERRO: nao alterar bibliotecas originais"; exit 1;; esac
  if readelf -d "$lib" | grep -Eq '\(RPATH\)|\(RUNPATH\)'; then
    echo "LIMPANDO: $(basename "$lib")"
    patchelf --remove-rpath "$lib"
  fi
done
bash "$ROOT/auditar-apk-zelda-scarletnx-2026-termux.sh"
