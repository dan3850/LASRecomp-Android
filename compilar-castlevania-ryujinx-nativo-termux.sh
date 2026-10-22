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
[ -s "$LIB" ] || {
  echo "ERRO: a biblioteca real Ryujinx NativeAOT sumiu: $LIB" >&2
  echo "Rode antes: bash testar-ryujinx-nativo-termux.sh" >&2
  exit 1
}
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
echo "Modo: SHADOW DIAGNOSTIC, Vulkan original mantido"
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
echo "No launcher, ligue 'Tradutor Ryujinx NativeAOT (diagnostico)'"
echo "Esta rodada verifica tradutor real DENTRO do jogo; nao substitui ainda a renderizacao."
