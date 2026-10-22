#!/data/data/com.termux/files/usr/bin/bash
# EXPERIMENTAL: first real Android-game-process Ryujinx shader port.
# NativeAOT can now adapt failed Maxwell fragment shaders into live Vulkan
# modules after ABI/descriptor validation. No per-shader .snxrbr packs.
# Preserves the previous app APK and game AOT; reuses CMake/Ninja caches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = experimental/ryujinx-runtime-nativeaot ] || {
  echo "ERRO: branch experimental/ryujinx-runtime-nativeaot necessaria" >&2
  exit 1
}
LIB="$HOME/ryujinx-nativeaot/libRyujinxShaderNative.so"
# A valid ABI does NOT prove that a cached library contains the latest C#.
# Fail closed: require a freshly selected workflow artifact on every build.
if [ "$#" -ne 1 ] || [ ! -s "$1" ]; then
  echo "ERRO: informe o ZIP NativeAOT gerado pelo GitHub Actions para este commit." >&2
  echo "Uso: bash compilar-castlevania-ryujinx-nativo-termux.sh /storage/emulated/0/Download/ryujinx-android-arm64-nativeaot.zip" >&2
  echo "Nao reutilizaremos automaticamente a biblioteca antiga." >&2
  exit 2
fi
ARTIFACT="$1"
TEMP_SO="$HOME/ryujinx-nativeaot/libRyujinxShaderNative-NEW.so"
mkdir -p "$(dirname "$LIB")"
rm -f "$TEMP_SO"
python3 "$ROOT/tools/ryujinx-nativeaot/extract_artifact.py" "$ARTIFACT" --out "$TEMP_SO"
python3 "$ROOT/tools/ryujinx-nativeaot/check_native_elf.py" "$TEMP_SO"
llvm-readelf -W --dyn-syms "$TEMP_SO" | grep -F 'snx_ryu_translate_scarlet_v1' >/dev/null || {
  echo "ERRO: adaptador Vulkan ausente do ZIP." >&2
  exit 1
}
mv -f "$TEMP_SO" "$LIB"
echo "===== IDENTIDADE DA BIBLIOTECA ====="
sha256sum "$ARTIFACT" "$LIB"
echo "ZIP escolhido explicitamente: $ARTIFACT"
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
