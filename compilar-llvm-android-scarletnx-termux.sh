#!/data/data/com.termux/files/usr/bin/bash
# Corrige busca de bibliotecas no NDK adaptado ao Termux, sem modificar o NDK.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="$ROOT/ScarletNX"
NDK="${ANDROID_NDK_ROOT:-$HOME/android-sdk/ndk/28.2.13676358}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_NDK_ROOT="$NDK"
LIB="$NDK/toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33"
LLVM="$ROOT/android-llvm/arm64-v8a"
LOG="$ROOT/logs/llvm-android-build.log"
[[ -f "$SRC/scripts/android-llvm.sh" && -f "$LIB/libunwind.a" && -f "$LIB/libatomic.a" ]] || {
  echo "ERRO: fonte ScarletNX ou bibliotecas ARM64 do NDK nao encontradas"; exit 1;
}
mkdir -p "$(dirname "$LOG")"
echo "=== TESTE RAPIDO DO LINKER ==="
printf 'int main(void){return 0;}\n' > "$ROOT/ndk-link-test.c"
"$NDK/toolchains/llvm/prebuilt/bin/clang" --target=aarch64-none-linux-android24 \
  --sysroot="$NDK/toolchains/llvm/prebuilt/sysroot" -L"$LIB" \
  "$ROOT/ndk-link-test.c" -o "$ROOT/ndk-link-test"
file "$ROOT/ndk-link-test"
echo "=== COMPILANDO LLVM ANDROID ==="
echo "Log: $LOG"
# CMAKE_EXE_LINKER_FLAGS reaches CMake's compiler sanity checks and LLVM's executable links.
# Also pass flags to shared/module links for consistency. Do not alter sysroot files.
set -o pipefail
(
 cd "$SRC"
 LLVM_VERSION=23.1.3 bash scripts/android-llvm.sh arm64-v8a "$LLVM" -- \
   "-DCMAKE_EXE_LINKER_FLAGS=-L$LIB" \
   "-DCMAKE_SHARED_LINKER_FLAGS=-L$LIB" \
   "-DCMAKE_MODULE_LINKER_FLAGS=-L$LIB"
) 2>&1 | tee "$LOG"
test -f "$LLVM/lib/cmake/llvm/LLVMConfig.cmake"
echo "LLVM_ANDROID_PRONTO=$LLVM"
