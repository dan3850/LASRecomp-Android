#!/data/data/com.termux/files/usr/bin/bash
# Preflight for clean ScarletNX Zelda baseline; never runs the old pinned builder.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
TARGET=05324b57629d0894506b31beb2c72869138b7ad1
cd "$ROOT"
[ "$(git branch --show-current)" = android/scarletnx-full-upgrade ] || {
  echo "ERRO: branch incorreta"; exit 1;
}
[ -d "$SRC/.git" ] || {
  echo "Fonte nova ausente; execute: bash preparar-scarletnx-completo-termux.sh"; exit 1;
}
[ "$(git -C "$SRC" rev-parse HEAD)" = "$TARGET" ] || {
  echo "ERRO: ScarletNX nao esta na revisao auditada"; exit 1;
}
python3 "$ROOT/tools/auditar_scarletnx_novo.py" "$SRC"
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC" --check
echo "PREFLIGHT_OK: fonte nova e ancora RomFS verificadas."
echo "NAO E APK: build Android novo, ABI e boot ainda precisam de validacao."
echo "Nao execute compilar-zelda-nxnative-graficos-termux.sh como teste da base nova: ele usa o runtime antigo."
