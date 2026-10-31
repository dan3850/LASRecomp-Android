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
export GRADLE="${GRADLE:-gradle}"
for cmd in cmake ninja "$GRADLE" javac; do command -v "$cmd" >/dev/null || { echo "ERRO: ferramenta ausente: $cmd"; exit 1; }; done
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
bash "$SRC/scripts/android-apk.sh" "$OUT" "$LLVM" arm64-v8a
echo "=== APKS GERADOS ==="
find "$OUT/stage/gradle/outputs/apk" -type f -name '*.apk' -print
echo "NOTA: o APK e o app original. O Zelda AOT permanece no staging privado e deve ser importado para games/ pelo app."
