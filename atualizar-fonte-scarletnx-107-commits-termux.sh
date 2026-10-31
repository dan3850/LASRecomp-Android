#!/data/data/com.termux/files/usr/bin/bash
# Move the independent ScarletNX source to the verified 2026-10-31 upstream revision.
# Do not touch the Zelda APK, AOT module, or existing native build.
set -euo pipefail
SRC="$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX"
TARGET=94b1a167eb68f141436460d3948a55d271a024ae
REPORT="$HOME/storage/downloads/ScarletNX-107-commits-upgrade.txt"
mkdir -p "$(dirname "$REPORT")"
[ -d "$SRC/.git" ] || { echo "ERRO: checkout ScarletNX nao encontrado"; exit 1; }
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "ERRO: alteracoes locais detectadas; nao vou sobrescrever"; exit 1; }
OLD="$(git -C "$SRC" rev-parse HEAD)"
git -C "$SRC" fetch origin main
[ "$(git -C "$SRC" rev-parse origin/main)" = "$TARGET" ] || { echo "ERRO: main oficial mudou. Atualizacao cancelada para nao usar commit nao verificado."; exit 1; }
git -C "$SRC" merge-base --is-ancestor 05324b57629d0894506b31beb2c72869138b7ad1 "$TARGET" || { echo "ERRO: historico inesperado"; exit 1; }
git -C "$SRC" checkout --detach "$TARGET"
{
 echo "SCARLETNX_SOURCE_UPGRADED=YES"
 echo "OLD_CHECKOUT=$OLD"
 echo "NEW_CHECKOUT=$(git -C "$SRC" rev-parse HEAD)"
 echo "NEW_COMMITS=$(git -C "$SRC" rev-list --count 05324b57629d0894506b31beb2c72869138b7ad1.."$TARGET")"
 echo "EXISTING_APK_AND_AOT_UNCHANGED=YES"
 echo "BUILD_STATUS=NOT_BUILT"
 echo "NEXT=Reconfigure native build for updated sources; rebuild and verify ABI before APK"
} > "$REPORT"
cat "$REPORT"
