#!/data/data/com.termux/files/usr/bin/bash
# Build a diagnostic runtime only (not the 251 MB Zelda AOT game).
# Preserves the proven booting DejaVu APK and emits a separate APK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
test "$(git branch --show-current)" = "experimental/zelda-links-awakening-ryujinx-nativeaot" || {
  echo "ERRO: branch Zelda incorreta" >&2
  exit 1
}
python3 -m unittest discover -s tests -p 'test_scarletnx_zelda60_diag.py'
export SCARLETNX_ZELDA_60FPS_DIAG=1
bash "$ROOT/compilar-zelda-ryujinx-termux.sh"
echo "Abra o APK FPS-ID-DIAG, entre no jogo, use Salvar log e envie o log."
