#!/data/data/com.termux/files/usr/bin/bash
# Resolve runtime ARM64 e libc++ do NDK adaptado ao Termux.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="$ROOT/ScarletNX"
NDK="${ANDROID_NDK_ROOT:-$HOME/android-sdk/ndk/28.2.13676358}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_NDK_ROOT="$NDK"
SYSROOT="$NDK/toolchains/llvm/prebuilt/sysroot"
LIB="$NDK/toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33"
LLVM="$ROOT/android-llvm/arm64-v8a"
LOG="$ROOT/logs/llvm-android-build.log"
[[ -f "$SRC/scripts/android-llvm.sh" && -f "$LIB/libunwind.a" && -f "$LIB/libatomic.a" ]] || {
 echo "ERRO: fontes ou runtime ARM64 do NDK ausentes"; exit 1;
}
# O NDK possui libc++_shared.so normalmente em sysroot/usr/lib/<triple>.
CXXLIB=""
for candidate in "$SYSROOT/usr/lib/aarch64-linux-android" "$SYSROOT/usr/lib/aarch64-linux-android/21" "$SYSROOT/usr/lib/aarch64-linux-android/24" "$NDK/toolchains/llvm/prebuilt/lib"; do
 if [[ -f "$candidate/libc++_shared.so" ]]; then CXXLIB="$candidate"; break; fi
done
if [[ -z "$CXXLIB" ]]; then
 echo "ERRO: libc++_shared.so nao encontrada nos caminhos do NDK."
 echo "Localizacoes disponiveis:"
 find "$NDK" -name 'libc++_shared.so' -print | head -20
 exit 1
fi
LINK_FLAGS="-L$LIB -L$CXXLIB"
mkdir -p "$(dirname "$LOG")"
echo "=== TESTANDO C E C++ ==="
printf 'int main(void){return 0;}\n' > "$ROOT/ndk-link-test.c"
printf 'int main(){return 0;}\n' > "$ROOT/ndk-link-test.cpp"
"$NDK/toolchains/llvm/prebuilt/bin/clang" --target=aarch64-none-linux-android24 --sysroot="$SYSROOT" $LINK_FLAGS "$ROOT/ndk-link-test.c" -o "$ROOT/ndk-link-test"
"$NDK/toolchains/llvm/prebuilt/bin/clang++" --target=aarch64-none-linux-android24 --sysroot="$SYSROOT" $LINK_FLAGS "$ROOT/ndk-link-test.cpp" -o "$ROOT/ndk-link-test-cxx"
file "$ROOT/ndk-link-test-cxx"
echo "=== TESTANDO LINKER C++ SEM FLAG LEGADA ==="
if ! "$NDK/toolchains/llvm/prebuilt/bin/clang++" \
 --target=aarch64-none-linux-android24 --sysroot="$SYSROOT" \
 $LINK_FLAGS "$ROOT/ndk-link-test.cpp" \
 -latomic -lm -o "$ROOT/ndk-link-test-cmake"; then
 echo "ERRO: O linker C++ continua falhando sem a flag legada."
 echo "Verificando libc++ e links simbolicos:"
 ls -l "$CXXLIB/libc++_shared.so" "$SYSROOT/usr/lib/aarch64-linux-android/21/libc++_shared.so" 2>&1 || true
 echo "Bibliotecas libc++ existentes:"
 find "$NDK/toolchains/llvm/prebuilt" -name 'libc++_shared.so' -o -name 'libc++_static.a' | head -30
 echo "Nao iniciar LLVM antes de resolver este teste."
 exit 1
fi
echo "LINKER_CMAKE_OK"
echo "=== COMPILANDO LLVM ANDROID (API 24) ==="
echo "Bibliotecas C++: $CXXLIB"
echo "Log: $LOG"
(
 cd "$SRC"
 LLVM_VERSION=23.1.3 bash scripts/android-llvm.sh arm64-v8a "$LLVM" -- \
  "-DANDROID_PLATFORM=android-24" \
  "-DCMAKE_EXE_LINKER_FLAGS=$LINK_FLAGS" \
  "-DCMAKE_SHARED_LINKER_FLAGS=$LINK_FLAGS" \
  "-DCMAKE_MODULE_LINKER_FLAGS=$LINK_FLAGS"
) 2>&1 | tee "$LOG"
test -f "$LLVM/lib/cmake/llvm/LLVMConfig.cmake"
echo "LLVM_ANDROID_PRONTO=$LLVM"
