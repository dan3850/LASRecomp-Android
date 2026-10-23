#!/data/data/com.termux/files/usr/bin/bash
# EXPERIMENTAL: first real Android-game-process Ryujinx shader port.
# NativeAOT can now adapt failed Maxwell fragment shaders into live Vulkan
# modules after ABI/descriptor validation. No per-shader .snxrbr packs.
# Preserves the previous app APK and game AOT; reuses CMake/Ninja caches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = experimental/zelda-links-awakening-ryujinx-nativeaot ] || {
  echo "ERRO: branch experimental/zelda-links-awakening-ryujinx-nativeaot necessaria" >&2
  exit 1
}
LIB="$HOME/ryujinx-nativeaot/libRyujinxShaderNative.so"
# Termux-only Zelda experiment: reuse the already available NativeAOT ELF.
# Optional ZIP input can replace it; never require GitHub Actions.
if [ "$#" -gt 1 ]; then
  echo "Uso: bash compilar-zelda-ryujinx-termux.sh [NativeAOT.zip]" >&2
  exit 2
fi
if [ "$#" -eq 1 ]; then
  [ -s "$1" ] || { echo "ZIP inexistente: $1" >&2; exit 1; }
  TEMP_SO="$HOME/ryujinx-nativeaot/libRyujinxShaderNative-NEW.so"
  mkdir -p "$(dirname "$LIB")"
  python3 "$ROOT/tools/ryujinx-nativeaot/extract_artifact.py" "$1" --out "$TEMP_SO"
  python3 "$ROOT/tools/ryujinx-nativeaot/check_native_elf.py" "$TEMP_SO"
  mv -f "$TEMP_SO" "$LIB"
fi
[ -s "$LIB" ] || {
  echo "ERRO: NativeAOT nao existe em $LIB. Nao e possivel construir este modo sem o tradutor." >&2
  exit 1
}
python3 "$ROOT/tools/ryujinx-nativeaot/check_native_elf.py" "$LIB"
llvm-readelf -W --dyn-syms "$LIB" | grep -F 'snx_ryu_translate_scarlet_v1' >/dev/null || {
  echo "ERRO: NativeAOT sem a funcao do adaptador Vulkan" >&2
  exit 1
}
echo "Biblioteca NativeAOT local (versao NAO comprovada pelo hash do codigo):"
sha256sum "$LIB"
python3 -m unittest discover -s tests -p 'test_ryujinx_live_probe_patch.py'
python3 -m unittest discover -s tests -p 'test_ryujinx_nativeaot_artifact.py'
python3 -m unittest discover -s tests -p 'test_ryujinx_native_job_parity.py'

# Zelda has no shader capture yet. Do not require Castlevania captures.
# Tests of the adapter's ABI and packaging still run above.
FOLDER="/storage/emulated/0/Download/ZeldaRecomp"
OLD="$FOLDER/Zelda-SNX-Runtime-TESTE.apk"
BACKUP="$FOLDER/Zelda-SNX-Runtime-ANTES-RYU-NATIVO.apk"
SEPARATE="$FOLDER/Zelda-SNX-Runtime-RYUJINX-NATIVO-TESTE.apk"
FONT_TEST="$FOLDER/Zelda-SNX-Runtime-DEJAVU-TESTE.apk"
FONT_BACKUP="$FOLDER/Zelda-SNX-Runtime-ANTES-DEJAVU.apk"
mkdir -p "$FOLDER"
if [ "${SCARLETNX_ZELDA_DEJAVU_FONT:-0}" = 1 ] &&
   [ -s "$OLD" ] && [ ! -e "$FONT_BACKUP" ]; then
  cp -p "$OLD" "$FONT_BACKUP"
  echo "APK anterior preservado: $FONT_BACKUP"
fi
if [ -s "$OLD" ] && [ ! -e "$BACKUP" ]; then
  cp -p "$OLD" "$BACKUP"
  echo "APK anterior preservado: $BACKUP"
fi

export SCARLETNX_RYU_NATIVE_PROBE_BUILD=1
export SCARLETNX_RYU_NATIVE_SO="$LIB"
unset SCARLETNX_RYUJINX_BRIDGE
echo "==========================================="
echo "RYUJINX REAL NO PROCESSO DO ZELDA"
echo "NativeAOT Android ARM64: C# original, sem packs"
echo "Modo: VULKAN REAL - Ryujinx adaptado, fallback ScarletNX"
echo "AOT do jogo: REUTILIZADO; sem clean"
echo "Biblioteca: $LIB"
echo "==========================================="
bash "$ROOT/compilar-castlevania-shader-termux.sh"

if [ ! -s "$OLD" ]; then
  echo "ERRO: APK experimental nao produzido" >&2
  exit 1
fi
if [ "${SCARLETNX_ZELDA_DEJAVU_FONT:-0}" = 1 ]; then
  cp -p "$OLD" "$FONT_TEST"
  echo "===== APK ZELDA DEJAVU ABI 12 ====="
  echo "$FONT_TEST"
else
  cp -p "$OLD" "$SEPARATE"
  echo "===== APK DE TESTE NATIVO ====="
  echo "$SEPARATE"
fi
echo "Back-up anterior: $BACKUP"
echo "No launcher, ligue 'Ryujinx Vulkan automatico (experimental)'"
echo "Esta rodada usa de verdade o SPIR-V adaptado no Vulkan para shaders que o ScarletNX rejeitar."
