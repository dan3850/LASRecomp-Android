#!/data/data/com.termux/files/usr/bin/bash
# Build the pinned ScarletNX Android arm64 runtime with external RomFS graft.
# Does not rebuild the 107 MB Mario AOT module or discard existing build caches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
die() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }
test "$(uname -m)" = aarch64 || die "Execute em Termux ARM64"
for tool in git python3 cmake ninja clang; do
  command -v "$tool" >/dev/null || die "Ferramenta ausente: $tool (pkg install git python cmake ninja clang)"
done

BASE="$HOME/.cache/lasrecomp-scarletnx-romfs"
SRC="$BASE/ScarletNX"
BUILD="$BASE/android-arm64-build"
LLVM_PREFIX="${SCARLETNX_LLVM_PREFIX:-$BASE/android-llvm/arm64-v8a}"
OUT="$HOME/scarletnx-romfs-build/libscarletnx.so"
COMMIT=34853eeae5af132e320adbb0193f13344085bf89
JOBS="${SCARLETNX_BUILD_JOBS:-4}"

# The current NDK is already used by the project's existing Termux builds.
if [ -z "${ANDROID_NDK_ROOT:-}" ]; then
  for candidate in "${ANDROID_HOME:-$HOME/Android/Sdk}"/ndk/* "$HOME/android-sdk/ndk/"*; do
    if [ -f "$candidate/build/cmake/android.toolchain.cmake" ]; then
      ANDROID_NDK_ROOT="$candidate"
    fi
  done
fi
export ANDROID_NDK_ROOT="${ANDROID_NDK_ROOT:-}"
[ -f "$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" ] ||
  die "NDK nao encontrado. Defina ANDROID_NDK_ROOT apontando para NDK r28c."
mkdir -p "$BASE" "$(dirname "$OUT")"

if [ ! -d "$SRC/.git" ]; then
  echo "Obtendo codigo ScarletNX original..."
  git clone --filter=blob:none https://github.com/scarletnx/ScarletNX.git "$SRC"
fi
cd "$SRC"
if [ "$(git rev-parse HEAD)" != "$COMMIT" ]; then
  [ -z "$(git status --porcelain)" ] || die "Fonte ScarletNX modificada no cache: $SRC"
  git fetch --depth 1 origin "$COMMIT"
  git checkout --detach "$COMMIT"
fi

python3 "$ROOT/tools/patch_scarletnx_romfs.py" "$SRC"

if [ ! -f "$LLVM_PREFIX/lib/cmake/llvm/LLVMConfig.cmake" ]; then
  echo "LLVM Android para o ScarletNX ausente. Compilando uma unica vez; essa etapa pode ser longa."
  echo "Pasta de cache: $LLVM_PREFIX"
  # Upstream builds just the ARM64 LLVM libraries needed by the recompiler.
  (cd "$SRC" && CMAKE_BUILD_PARALLEL_LEVEL="$JOBS" \
      scripts/android-llvm.sh arm64-v8a "$LLVM_PREFIX")
fi
[ -f "$LLVM_PREFIX/lib/cmake/llvm/LLVMConfig.cmake" ] ||
  die "LLVM ARM64 nao foi instalado corretamente: $LLVM_PREFIX"

echo "Configurando ScarletNX ARM64 com RomFS externa..."
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
  -DLLVM_DIR="$LLVM_PREFIX/lib/cmake/llvm" \
  -DSNX_DEPLOY=OFF -DSNX_BUILD_GNUABI=OFF -DBUILD_TESTING=OFF \
  -DCMAKE_BUILD_TYPE=Release

echo "Compilando somente a biblioteca ScarletNX (mantendo o cache)..."
cmake --build "$BUILD" --target scarletnx --parallel "$JOBS"
RUNTIME="$BUILD/src/nx/libscarletnx.so"
[ -s "$RUNTIME" ] || RUNTIME="$(find "$BUILD" -name libscarletnx.so -type f -print -quit)"
[ -s "$RUNTIME" ] || die "Compilacao terminou mas libscarletnx.so nao encontrada"
grep -aF 'SNX_EXTERNAL_ROMFS' "$RUNTIME" >/dev/null ||
  die "Build sem suporte ao graft. Bibliotecas originais nao serao substituidas."
cp "$RUNTIME" "$OUT"
echo "===== SCARLETNX MODIFICADO PRONTO ====="
ls -lh "$OUT"
echo "===== COMPILANDO APK MARIO ====="
cd "$ROOT"
export SCARLETNX_PATCHED_RUNTIME_SO="$OUT"
bash compilar-mario-snx-runtime-termux.sh
