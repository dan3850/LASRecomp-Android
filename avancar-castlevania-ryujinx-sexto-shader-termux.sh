#!/data/data/com.termux/files/usr/bin/bash
# Add the exact sixth failing fragment shader without dropping the first five.
# Local game shader data stays in Termux and Downloads, never in Git.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ "$(git branch --show-current)" != experimental/castlevania-belmonts-curse ]; then
  echo "ERRO: use a branch experimental/castlevania-belmonts-curse" >&2
  exit 1
fi
set -- /storage/emulated/0/Download/Castlevania-shaders-SNXS*.zip
if [ ! -s "$1" ]; then
  echo "ERRO: ZIP de shaders ausente. Exporte os shaders no launcher do Castlevania." >&2
  exit 1
fi
OUT="$HOME/castlevania-ryujinx-six"
mkdir -p "$OUT"
{
  echo "===== PROVA DO SEXTO SHADER ====="
  echo "ZIPs localizados: $#"
  python3 -m unittest discover -s tests -p 'test_castlevania_extend_ryujinx.py'
  python3 -m unittest discover -s tests -p 'test_castlevania_ryujinx_pack.py'
  python3 "$ROOT/tools/castlevania_extend_ryujinx.py" "$@"
  echo "===== SHADERS VALIDADOS. COMPILANDO RUNTIME INCREMENTAL ====="
  bash "$ROOT/compilar-castlevania-ryujinx-termux.sh"
  echo "===== TESTE DISPONIVEL ====="
  echo "APK: /storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk"
  echo "Importe: /storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-Ryujinx-Ponte-6.snxrbr"
  echo "Os cinco shaders originais continuam no novo pacote."
} 2>&1 | tee "$OUT/six-integration.log"
