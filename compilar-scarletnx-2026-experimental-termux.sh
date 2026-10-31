#!/data/data/com.termux/files/usr/bin/bash
# Experimental ScarletNX 2026 ARM64 build; never installs or replaces stable APK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = android/scarletnx-full-upgrade ] || { echo "ERRO: branch incorreta"; exit 1; }
for t in cmake ninja clang python3 llvm-readelf; do command -v "$t" >/dev/null || { echo "ERRO: falta $t"; exit 1; }; done
BASE="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="${SCARLETNX_UPGRADE_SOURCE:-$BASE/ScarletNX}"
BUILD="$BASE/android-arm64-build-2026"
OUT="$BASE/output/libscarletnx.so"
[ "$(git -C "$SRC" rev-parse HEAD)" = 05324b57629d0894506b31beb2c72869138b7ad1 ] || { echo "ERRO: revisao inesperada"; exit 1; }
grep -q LASRECOMP_ANDROID_2026_LINK "$SRC/src/multicall/CMakeLists.txt" || { echo "ERRO: prepare primeiro o linker"; exit 1; }
grep -q SNX_EXTERNAL_ROMFS "$SRC/src/nx/hle/filesystem/fs.c" || { echo "ERRO: RomFS ausente"; exit 1; }
grep -q SNX_TERMUX_NATIVE_LLVM "$SRC/cmake/llvm.cmake" || { echo "ERRO: LLVM ausente"; exit 1; }
if [ -z "${ANDROID_NDK_ROOT:-}" ]; then
  for candidate in "${ANDROID_HOME:-$HOME/Android/Sdk}"/ndk/* "$HOME/android-sdk/ndk/"*; do
    if [ -f "$candidate/build/cmake/android.toolchain.cmake" ]; then ANDROID_NDK_ROOT="$candidate"; fi
  done
fi
[ -f "${ANDROID_NDK_ROOT:-}/build/cmake/android.toolchain.cmake" ] || { echo "ERRO: NDK ausente"; exit 1; }
export ANDROID_NDK_ROOT ANDROID_NDK_HOME="$ANDROID_NDK_ROOT"
NDK_LIB="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot/usr/lib/aarch64-linux-android/26"
[ -s "$NDK_LIB/libc.so" ] || { echo "ERRO: libc Android26 ausente"; exit 1; }
[ -s "$PREFIX/lib/libc++_shared.so" ] || { echo "ERRO: libc++_shared.so Termux ausente"; exit 1; }
[ -x "$PREFIX/bin/llvm-config" ] || { echo "ERRO: llvm-config ausente"; exit 1; }
# FFmpeg runs its own configure, which does not inherit CMake's linker search directories.
UNWIND=""
while IFS= read -r candidate; do
  case "$candidate" in
    */aarch64/*|*/aarch64-linux-android/*|*/linux/*) UNWIND="$candidate"; break ;;
  esac
done < <(find "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt" -type f -name libunwind.a 2>/dev/null)
[ -n "$UNWIND" ] || { echo "ERRO: libunwind.a nao encontrada no NDK"; exit 1; }
python3 "$ROOT/tools/patch_scarletnx_ffmpeg_unwind_2026.py" "$SRC" "$(dirname "$UNWIND")"
echo "NDK_LIBUNWIND=$UNWIND"
mkdir -p "$BASE/output" "$BASE/logs"
LOG="$BASE/logs/build-$(date +%Y%m%d-%H%M%S).log"
echo "BUILD_LOG=$LOG"
JOBS="${SCARLETNX_BUILD_JOBS:-2}"
export CMAKE_BUILD_PARALLEL_LEVEL="$JOBS" MAKEFLAGS="-j$JOBS"
{
  cmake -S "$SRC" -B "$BUILD" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
    -DLLVM_DIR="$PREFIX/lib/cmake/llvm" \
    -DSNX_TERMUX_NATIVE_LLVM=ON -DSNX_LLVM_CONFIG="$PREFIX/bin/llvm-config" \
    -DCMAKE_EXE_LINKER_FLAGS="-L$NDK_LIB -L$PREFIX/lib" \
    -DCMAKE_CXX_FLAGS="-nostdlib++" \
    -DCMAKE_CXX_STANDARD_LIBRARIES="$PREFIX/lib/libc++_shared.so" \
    -DCMAKE_SHARED_LINKER_FLAGS="-L$NDK_LIB -L$PREFIX/lib" \
    -DCMAKE_MODULE_LINKER_FLAGS="-L$NDK_LIB -L$PREFIX/lib" \
    -DSNX_DEPLOY=OFF -DSNX_BUILD_GNUABI=OFF -DSNX_BUILD_3DS=OFF \
    -DSNX_BUILD_GUI=OFF -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD" --target scarletnx --parallel "$JOBS"
} 2>&1 | tee "$LOG"
RUNTIME="$BUILD/libscarletnx.so"
[ -s "$RUNTIME" ] || { echo "ERRO: biblioteca nao gerada"; exit 1; }
llvm-readelf -h "$RUNTIME" | grep -q 'AArch64' || { echo "ERRO: ELF nao e AArch64"; exit 1; }
llvm-readelf -d "$RUNTIME" > "$BASE/logs/needed-2026.txt"
grep -aF SNX_EXTERNAL_ROMFS "$RUNTIME" >/dev/null || { echo "ERRO: RomFS nao presente no ELF"; exit 1; }
cp "$RUNTIME" "$OUT"
echo "RUNTIME_EXPERIMENTAL_OK=$OUT"
echo "AVISO: ELF ainda nao validado em boot Android. Nenhum APK alterado."
