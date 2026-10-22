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
    python3 "$ROOT/tools/patch_scarletnx_bindless_diag.py" "$SRC" --revert || true
    python3 "$ROOT/tools/patch_scarletnx_fswzadd.py" "$SRC" --revert ||
      echo "AVISO: falha ao restaurar apenas o shader do cache ScarletNX" >&2
  fi
}
trap restore_source EXIT
python3 tests/test_castlevania_shader_patch.py
python3 tests/test_castlevania_bindless_diag.py
# Keep the known booting but graphically incomplete test APK for comparison.
OLD_APK="/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk"
BACKUP="/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-ANTES-FSWZADD.apk"
if [ -s "$OLD_APK" ] && [ ! -e "$BACKUP" ]; then
  cp -p "$OLD_APK" "$BACKUP"
  echo "APK experimental anterior preservado em: $BACKUP"
fi
if [ ! -s "$SRC/src/nx/gpu/shader/spirv_translate.c" ]; then
  echo "ERRO: fonte ScarletNX nao encontrado no cache; rode primeiro o build normal." >&2
  exit 1
fi
python3 "$ROOT/tools/patch_scarletnx_bindless_diag.py" "$SRC"
export SCARLETNX_CASTLEVANIA_FSWZADD=1
export SCARLETNX_RUNTIME_OUT="$OUT"
echo "============================================="
echo "CASTLEVANIA: shader FSWZADD 0xD7 experimental"
echo "Mario runtime estavel: NAO sera sobrescrito"
echo "AOT 603 MB reutilizado; nao recompilar blocos"
echo "Diagnostico bindless ativo: op, pc, reg, def, producer"
echo "============================================="
bash "$ROOT/compilar-mario-snx-romfs-termux.sh"
echo "===== VERSAO EXPERIMENTAL GERADA ====="
echo "Runtime: $OUT"
echo "APK: /storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk"
