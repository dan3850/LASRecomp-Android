#!/data/data/com.termux/files/usr/bin/bash
# Package user's 5 captures and SPIR-V locally. NEVER include game data in Git.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ "$(git branch --show-current)" != experimental/castlevania-belmonts-curse ]; then
  echo "ERRO: branch experimental necessaria" >&2
  exit 1
fi
CAPTURE=""
for file in /storage/emulated/0/Download/Castlevania-shaders-SNXS*.zip; do
  if [ -s "$file" ] && { [ -z "$CAPTURE" ] || [ "$file" -nt "$CAPTURE" ]; }; then CAPTURE="$file"; fi
done
if [ -z "$CAPTURE" ]; then
  echo "ERRO: capture ZIP nao encontrado em Downloads. Use o ZIP original com cinco .snxs." >&2
  exit 1
fi
BRIDGE="$HOME/castlevania-ryujinx-bridge"
test -s "$BRIDGE/bridge-manifest.json" || {
  echo "ERRO: valide primeiro com bash validar-castlevania-ryujinx-bridge-termux.sh" >&2
  exit 1
}
mkdir -p /storage/emulated/0/Download/CastlevaniaRecomp
OUT="/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-Ryujinx-Ponte.snxrbr"
python3 tools/package_castlevania_ryujinx_runtime.py \
  "$CAPTURE" --bridge "$BRIDGE" --out "$OUT"
echo "PACOTE PRIVADO: $OUT"
echo "Depois de instalar o APK experimental, importe esse arquivo pelo botao Ryujinx."
