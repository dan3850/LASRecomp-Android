#!/data/data/com.termux/files/usr/bin/bash
# Build official ScarletNX Android APK, without rebuilding Zelda AOT.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="$ROOT/ScarletNX"
OUT="$ROOT/scarletnx-android-apk-2026"
LLVM="$ROOT/android-llvm"
NDK="${ANDROID_NDK_ROOT:-}"
if [[ -z "$NDK" ]]; then
  SDK="${ANDROID_HOME:-$HOME/android-sdk}"
  NDK="$(find "$SDK/ndk" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -1)"
fi
[[ -f "$NDK/build/cmake/android.toolchain.cmake" ]] || { echo "ERRO: NDK Android nao encontrado"; exit 1; }
[[ -f "$SRC/scripts/android-apk.sh" ]] || { echo "ERRO: checkout ScarletNX ausente"; exit 1; }
[[ "$(git -C "$SRC" rev-parse HEAD)" == "05324b57629d0894506b31beb2c72869138b7ad1" ]] || { echo "ERRO: upstream nao corresponde a versao auditada"; exit 1; }
export ANDROID_NDK_ROOT="$NDK"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
if [[ -z "${GRADLE:-}" ]]; then
  if command -v gradle >/dev/null 2>&1; then GRADLE="$(command -v gradle)"
  else
    for candidate in "$HOME/gradle/bin/gradle" "$HOME/gradle-9.2.1/bin/gradle" "$HOME/gradle-9.1.0/bin/gradle" "$PREFIX/bin/gradle"; do
      if [[ -x "$candidate" ]]; then GRADLE="$candidate"; break; fi
    done
  fi
fi
if [[ -z "${GRADLE:-}" ]]; then
  echo "ERRO: Gradle nao encontrado. Procure: find \"\$HOME\" -maxdepth 5 -type f -path '*/bin/gradle' 2>/dev/null"
  echo "Defina GRADLE=/caminho/para/bin/gradle (Gradle 9)."
  exit 2
fi
export GRADLE
echo "Gradle localizado: $GRADLE"
for cmd in cmake ninja javac; do command -v "$cmd" >/dev/null || { echo "ERRO: ferramenta ausente: $cmd"; exit 1; }; done
if [[ ! -f "$LLVM/arm64-v8a/lib/cmake/llvm/LLVMConfig.cmake" ]]; then
  echo "=== LLVM ANDROID AINDA NAO COMPILADO ==="
  echo "O libLLVM.so do Termux nao substitui a toolchain LLVM NDK do APK."
  echo "Compile uma vez o LLVM Android oficial (pode consumir bastante tempo e espaco):"
  echo "  cd '$SRC'"
  echo "  ANDROID_NDK_ROOT='$NDK' ANDROID_HOME='$ANDROID_HOME' LLVM_VERSION=23.1.3 scripts/android-llvm.sh arm64-v8a '$LLVM/arm64-v8a'"
  exit 2
fi
echo "=== COMPILANDO APK ANDROID SCARLETNX (SEM RECOMPILAR ZELDA) ==="
mkdir -p "$OUT"
export SCARLETNX_BUILD_JOBS="${SCARLETNX_BUILD_JOBS:-2}"
# The official script chooses the device CPU count; keep build bounded via CMAKE_BUILD_PARALLEL_LEVEL.
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
# LLVM Android was compiled with API 24; the runtime must use the same API.
export ANDROID_API=24
LIB="$NDK/toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33"
SYSROOT="$NDK/toolchains/llvm/prebuilt/sysroot"
CXXLIB="$SYSROOT/usr/lib/aarch64-linux-android"
[[ -f "$LIB/libatomic.a" && -f "$LIB/libunwind.a" && -f "$CXXLIB/libc++_shared.so" ]] || {
  echo "ERRO: bibliotecas ARM64 do NDK incompletas"; exit 1;
}
LINK_FLAGS="-L$LIB -L$CXXLIB"
# Remove only CMake configuration from previous failed API 21 attempt.
if [[ -f "$OUT/arm64-v8a/CMakeCache.txt" ]] && grep -q 'ANDROID_PLATFORM:.*android-21' "$OUT/arm64-v8a/CMakeCache.txt"; then
  rm -f "$OUT/arm64-v8a/CMakeCache.txt"
fi
echo "Android API: $ANDROID_API"
echo "Bibliotecas NDK: $LINK_FLAGS"
bash "$SRC/scripts/android-apk.sh" "$OUT" "$LLVM" arm64-v8a -- \
  "-DCMAKE_EXE_LINKER_FLAGS=$LINK_FLAGS" \
  "-DCMAKE_SHARED_LINKER_FLAGS=$LINK_FLAGS" \
  "-DCMAKE_MODULE_LINKER_FLAGS=$LINK_FLAGS"
echo "=== APKS GERADOS ==="
find "$OUT/stage/gradle/outputs/apk" -type f -name '*.apk' -print
echo "NOTA: o APK e o app original. O Zelda AOT permanece no staging privado e deve ser importado para games/ pelo app."
