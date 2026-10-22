#!/data/data/com.termux/files/usr/bin/bash
# Build ABI 2 runtime/APK on Termux with an explicitly selected Actions NativeAOT.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
die() { echo "ERRO: $*" >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || die 'Execute no Termux ARM64.'
[ "$(git branch --show-current)" = experimental/ryujinx-runtime-nativeaot ] || die 'Branch experimental/ryujinx-runtime-nativeaot necessaria.'
[ "$#" -eq 1 ] && [ -s "$1" ] || die 'Uso: bash compilar-castlevania-ryujinx-v2-termux.sh /storage/emulated/0/Download/ryujinx-v2-COMMIT.zip'
ARTIFACT="$(realpath "$1")"
for tool in git python3 llvm-readelf cmake ninja clang; do
  command -v "$tool" >/dev/null || die "Ferramenta ausente: $tool"
done
SRC="$HOME/.cache/lasrecomp-scarletnx-romfs/ScarletNX"
[ -s "$SRC/src/nx/gpu/vk/pipeline.c" ] || die 'Cache ScarletNX ausente. Este script reutiliza a instalacao Termux e o cache dos builds anteriores.'
CACHE="$HOME/.cache/lasrecomp-ryujinx-v2"
NX="$CACHE/nxnative"
STAGE="$CACHE/source"
PIN=1eaaab88caffcc17ada94b6dbdbe4f3b02fbb480
mkdir -p "$CACHE"
if [ ! -d "$NX/.git" ]; then
  git clone --filter=blob:none --no-checkout https://github.com/seedds/nxnative "$NX"
  git -C "$NX" sparse-checkout set dm/gfx/tools/dmsh_xlate dm/third_party/ryujinx
fi
if ! git -C "$NX" cat-file -e "$PIN^{commit}" 2>/dev/null; then git -C "$NX" fetch origin "$PIN"; fi
git -C "$NX" checkout --detach "$PIN"
[ "$(git -C "$NX" rev-parse HEAD)" = "$PIN" ] || die 'Fonte nxnative fora da revisao fixada.'
git -C "$NX" diff --quiet HEAD -- dm/gfx/tools/dmsh_xlate dm/third_party/ryujinx || die 'Fonte nxnative modificada; identidade recusada.'
python3 tools/ryujinx-nativeaot/prepare_source.py --nxnative "$NX" --out "$STAGE"
LIB="$CACHE/libRyujinxShaderNative.so"
python3 tools/ryujinx-nativeaot/extract_artifact.py "$ARTIFACT" --out "$LIB"
python3 tools/ryujinx-nativeaot/check_native_elf.py "$LIB"
python3 tools/termux_ryujinx_v2.py "$LIB" --identity "$STAGE/build-identity.json"
if command -v spirv-val >/dev/null; then
  python3 tools/ryujinx-nativeaot/test_v2_native.py "$LIB" "$STAGE/build-identity.json" --out "$CACHE/native-tests"
else
  echo 'AVISO: spirv-val ausente; teste SPIR-V local nao executado (pkg install spirv-tools).'
fi
FOLDER=/storage/emulated/0/Download/CastlevaniaRecomp
OLD="$FOLDER/Castlevania-SNX-Runtime-TESTE.apk"
DEST="$FOLDER/Castlevania-SNX-Runtime-RYUJINX-V2-TESTE.apk"
mkdir -p "$FOLDER"
if [ -s "$OLD" ]; then cp -p "$OLD" "$FOLDER/Castlevania-SNX-Runtime-ANTES-V2-$(date +%Y%m%d-%H%M%S)-$$.apk"; fi
export SCARLETNX_RYU_NATIVE_PROBE_BUILD=1 SCARLETNX_RYU_V2=1
export SCARLETNX_RYU_NATIVE_SO="$LIB" SCARLETNX_RYU_V2_IDENTITY="$STAGE/build-identity.json"
unset SCARLETNX_RYUJINX_BRIDGE
echo 'ABI 2: recompilando runtime Vulkan e APK; AOT do jogo e caches preservados.'
bash "$ROOT/compilar-castlevania-shader-termux.sh"
python3 tools/termux_ryujinx_v2.py "$OLD" --identity "$SCARLETNX_RYU_V2_IDENTITY" \
  --revision "$(git rev-parse HEAD)" --library "$LIB"
cp -p "$OLD" "$DEST"
echo "APK ABI 2 verificada: $DEST"
echo "No launcher, ligue 'Ryujinx Vulkan automatico (experimental)'."
