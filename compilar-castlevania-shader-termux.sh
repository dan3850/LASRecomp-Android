#!/data/data/com.termux/files/usr/bin/bash
# Experimental Castlevania FSWZADD 0xD7 repair (incremental).
# Reuse pinned ScarletNX source/CMake/Ninja cache; preserve Mario runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [ "$(git branch --show-current)" != experimental/castlevania-belmonts-curse ]; then
  echo "ERRO: execute na branch experimental/castlevania-belmonts-curse" >&2
  exit 1
fi
SRC="$HOME/.cache/lasrecomp-scarletnx-romfs/ScarletNX"
OUT="$HOME/scarletnx-castlevania-shader-build/libscarletnx.so"
restore_source() {
  if [ -s "$SRC/src/nx/gpu/shader/spirv_translate.c" ]; then
    python3 "$ROOT/tools/patch_scarletnx_fswzadd.py" "$SRC" --revert ||
      echo "AVISO: falha ao restaurar apenas o shader do cache ScarletNX" >&2
  fi
}
trap restore_source EXIT
python3 tests/test_castlevania_shader_patch.py
export SCARLETNX_CASTLEVANIA_FSWZADD=1
export SCARLETNX_RUNTIME_OUT="$OUT"
echo "============================================="
echo "CASTLEVANIA: shader FSWZADD 0xD7 experimental"
echo "Mario runtime estavel: NAO sera sobrescrito"
echo "AOT 603 MB reutilizado; nao recompilar blocos"
echo "============================================="
bash "$ROOT/compilar-mario-snx-romfs-termux.sh"
echo "===== VERSAO EXPERIMENTAL GERADA ====="
echo "Runtime: $OUT"
echo "APK: /storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk"
