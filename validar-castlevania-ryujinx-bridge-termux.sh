#!/data/data/com.termux/files/usr/bin/bash
# Ryujinx -> ScarletNX OFFLINE Vulkan layout validation.
# Never recompiles game AOT, edits the ScarletNX source cache or installs APKs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ "$(git branch --show-current)" != experimental/castlevania-belmonts-curse ]; then
  echo "ERRO: execute na branch experimental/castlevania-belmonts-curse" >&2
  exit 1
fi
ZIP=""
if [ "$#" -gt 0 ]; then ZIP="$1"; fi
if [ -z "$ZIP" ]; then
  for file in /storage/emulated/0/Download/Castlevania-Ryujinx-Resultado*.zip; do
    if [ -s "$file" ] && { [ -z "$ZIP" ] || [ "$file" -nt "$ZIP" ]; }; then ZIP="$file"; fi
  done
fi
if [ ! -s "$ZIP" ]; then
  echo "ERRO: Castlevania-Ryujinx-Resultado.zip nao encontrado em Download." >&2
  exit 1
fi
if ! command -v spirv-val >/dev/null 2>&1; then
  echo "Instalando SPIR-V Tools (somente o validador, sem recompilar APK)..."
  pkg install -y spirv-tools
fi
OUT="$HOME/castlevania-ryujinx-bridge"
mkdir -p "$OUT"
python3 -m unittest discover -s tests -p test_ryujinx_spirv_bridge.py
echo "===== PREPARANDO MODULOS E VALIDANDO VULKAN 1.3 ====="
python3 "$ROOT/tools/ryujinx_spirv_bridge.py" "$ZIP" --out "$OUT" \
  2>&1 | tee "$OUT/bridge-validation.log"
echo "===== RESULTADO ====="
echo "$OUT/bridge-validation.log"
echo "$OUT/bridge-manifest.json"
echo "Nenhum APK, AOT ou runtime foi alterado."
