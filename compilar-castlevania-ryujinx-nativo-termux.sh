#!/data/data/com.termux/files/usr/bin/bash
# EXPERIMENTAL: first real Android-game-process Ryujinx shader port.
# NativeAOT translates failed Maxwell programs live but DOES NOT bind their
# SPIR-V to Vulkan yet. No individual shaders or .snxrbr files are required.
# Preserves the previous app APK and game AOT; reuses CMake/Ninja caches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = experimental/ryujinx-runtime-nativeaot ] || {
  echo "ERRO: branch experimental/ryujinx-runtime-nativeaot necessaria" >&2
  exit 1
}
LIB="$HOME/ryujinx-nativeaot/libRyujinxShaderNative.so"
# The original native library successfully translated 5/5 but has no Vulkan
# descriptor adapter export. Upgrade ONLY after verifying the newer archive.
is_vulkan_adapter() {
  [ -s "$1" ] &&
  llvm-readelf -W --dyn-syms "$1" 2>/dev/null |
    grep -F 'snx_ryu_translate_scarlet_v1' >/dev/null
}
if ! is_vulkan_adapter "$LIB"; then
  echo "Ryujinx antigo: procurando biblioteca NativeAOT com adaptador Vulkan em Download..."
  ARTIFACT=""
  for candidate in /storage/emulated/0/Download/ryujinx-android-arm64-vulkan-adapter*.zip \
                   /storage/emulated/0/Download/ryujinx-android-arm64-nativeaot*.zip; do
    if [ -s "$candidate" ] && { [ -z "$ARTIFACT" ] || [ "$candidate" -nt "$ARTIFACT" ]; }; then
      ARTIFACT="$candidate"
    fi
  done
  if [ -n "$ARTIFACT" ]; then
    TEMP_SO="$HOME/ryujinx-nativeaot/libRyujinxShaderNative-NEW.so"
    python3 "$ROOT/tools/ryujinx-nativeaot/extract_artifact.py" "$ARTIFACT" \
      --out "$TEMP_SO"
    if is_vulkan_adapter "$TEMP_SO"; then
      mv -f "$TEMP_SO" "$LIB"
      echo "NOVA biblioteca Ryujinx Vulkan verificada e instalada no cache."
    else
      echo "O ZIP em Download e da versao ANTIGA, sem adaptador Vulkan."
      rm -f "$TEMP_SO"
    fi
  fi
fi
if ! is_vulkan_adapter "$LIB"; then
  echo "ERRO: biblioteca com snx_ryu_translate_scarlet_v1 ainda nao disponivel." >&2
  echo "Baixe ryujinx-android-arm64-vulkan-adapter.zip e salve em Download." >&2
  echo "https://github.com/dan3850/LASRecomp-Android/actions/workflows/ryujinx-nativeaot-android.yml" >&2
  echo "O Castlevania anterior continua intacto. Nenhuma compilacao iniciada." >&2
  exit 1
fi
python3 "$ROOT/tools/ryujinx-nativeaot/check_native_elf.py" "$LIB"
python3 -m unittest discover -s tests -p 'test_ryujinx_live_probe_patch.py'
python3 -m unittest discover -s tests -p 'test_ryujinx_nativeaot_artifact.py'
python3 -m unittest discover -s tests -p 'test_ryujinx_native_job_parity.py'

# A cheap, REAL C ABI check must pass with the exact live JSON/options before
# rebuilding ScarletNX. This catches regressions like debug:false immediately.
CAPTURE=""
for candidate in /storage/emulated/0/Download/Castlevania-shaders-SNXS*.zip; do
  if [ -s "$candidate" ]; then CAPTURE="$candidate"; break; fi
done
[ -n "$CAPTURE" ] || {
  echo "ERRO: ZIP antigo com shaders Maxwell para teste de regressao nao localizado." >&2
  echo "Ele NAO sera embutido na APK; apenas valida o tradutor antes do build." >&2
  exit 1
}
echo "===== REGRESSAO RYUJINX REAL: MESMAS OPCOES DO JOGO ====="
python3 "$ROOT/tools/ryujinx-nativeaot/test_native.py" "$LIB" "$CAPTURE" \
  --out "$HOME/ryujinx-nativeaot/live-parity-test" || {
  echo "ERRO: prova do Ryujinx falhou; nenhuma APK sera recompilada." >&2
  exit 1
}
echo "===== PROVA: ADAPTADOR VULKAN REAL == PYTHON OFFLINE ====="
python3 "$ROOT/tools/ryujinx-nativeaot/test_scarlet_adapter_native.py" \
  "$LIB" "$CAPTURE" --out "$HOME/ryujinx-nativeaot/vulkan-adapter-test" || {
  echo "ERRO: tradutor dinamico NAO corresponde ao SPIR-V validado." >&2
  echo "Nenhuma APK sera recompilada enquanto isso nao for corrigido." >&2
  exit 1
}

FOLDER="/storage/emulated/0/Download/CastlevaniaRecomp"
OLD="$FOLDER/Castlevania-SNX-Runtime-TESTE.apk"
BACKUP="$FOLDER/Castlevania-SNX-Runtime-ANTES-RYU-NATIVO.apk"
SEPARATE="$FOLDER/Castlevania-SNX-Runtime-RYUJINX-NATIVO-TESTE.apk"
mkdir -p "$FOLDER"
if [ -s "$OLD" ] && [ ! -e "$BACKUP" ]; then
  cp -p "$OLD" "$BACKUP"
  echo "APK anterior preservado: $BACKUP"
fi

export SCARLETNX_RYU_NATIVE_PROBE_BUILD=1
export SCARLETNX_RYU_NATIVE_SO="$LIB"
unset SCARLETNX_RYUJINX_BRIDGE
echo "==========================================="
echo "RYUJINX REAL NO PROCESSO DO CASTLEVANIA"
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
cp -p "$OLD" "$SEPARATE"
echo "===== APK DE TESTE NATIVO ====="
echo "$SEPARATE"
echo "Back-up anterior: $BACKUP"
echo "No launcher, ligue 'Ryujinx Vulkan automatico (experimental)'"
echo "Esta rodada usa de verdade o SPIR-V adaptado no Vulkan para shaders que o ScarletNX rejeitar."
