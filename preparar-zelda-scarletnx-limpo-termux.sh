#!/data/data/com.termux/files/usr/bin/bash
# Prepare only clean upstream ScarletNX plus the two audited Android compatibility patches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
TARGET=05324b57629d0894506b31beb2c72869138b7ad1
cd "$ROOT"
[ "$(git branch --show-current)" = android/scarletnx-full-upgrade ] || {
  echo "ERRO: branch incorreta"; exit 1;
}
if [ ! -d "$SRC/.git" ]; then
  bash "$ROOT/preparar-scarletnx-completo-termux.sh"
fi
[ "$(git -C "$SRC" rev-parse HEAD)" = "$TARGET" ] || {
  echo "ERRO: revisao ScarletNX incorreta"; exit 1;
}
# Only these two files may be locally modified. Never reset an existing checkout.
STATUS="$(git -C "$SRC" status --porcelain)"
if [ -n "$STATUS" ]; then
  while IFS= read -r entry; do
    case "$entry" in
      " M cmake/llvm.cmake"|" M src/nx/hle/filesystem/fs.c") ;;
      *) echo "ERRO: alteracao inesperada: $entry"; exit 1 ;;
    esac
  done <<< "$STATUS"
fi
python3 "$ROOT/tools/patch_scarletnx_llvm_2026.py" "$SRC" --check
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC" --check
python3 "$ROOT/tools/patch_scarletnx_llvm_2026.py" "$SRC"
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC"
python3 "$ROOT/tools/auditar_build_scarletnx_2026.py" "$SRC"
echo "PREPARACAO_OK: somente LLVM Termux e RomFS Android; nenhum patch grafico antigo."
echo "FONTE: $SRC"
echo "Nenhuma biblioteca ou APK compilado."
