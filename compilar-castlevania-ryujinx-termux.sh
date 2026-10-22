#!/data/data/com.termux/files/usr/bin/bash
# Incremental experimental Ryujinx bridge build, preserving prior APK and AOT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ "$(git branch --show-current)" != experimental/castlevania-belmonts-curse ]; then
  echo "ERRO: usar experimental/castlevania-belmonts-curse" >&2
  exit 1
fi
APK="/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk"
BACKUP="/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-ANTES-RYUJINX.apk"
if [ -s "$APK" ] && [ ! -e "$BACKUP" ]; then
  cp -p "$APK" "$BACKUP"
  echo "APK anterior preservado em: $BACKUP"
fi
export SCARLETNX_RYUJINX_BRIDGE=1
echo "Bridge Ryujinx: compilacao INCREMENTAL, sem novo AOT."
bash "$ROOT/compilar-castlevania-shader-termux.sh"
echo "===== APK PARA TESTE ====="
echo "$APK"
echo "Bridge DESLIGADA por padrao; importe o pack e ligue no launcher se quiser testar."
