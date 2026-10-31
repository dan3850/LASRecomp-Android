#!/data/data/com.termux/files/usr/bin/bash
# Native Termux Switch AOT generator, isolated from the Android runtime build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ "$(git -C "$ROOT" branch --show-current)" = android/scarletnx-full-upgrade ] || { echo "ERRO: branch incorreta"; exit 1; }
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
BUILD="$HOME/.cache/lasrecomp-scarletnx-upgrade/termux-aot-tools-native-2026"
[ "$(git -C "$SRC" rev-parse HEAD)" = 05324b57629d0894506b31beb2c72869138b7ad1 ] || { echo "ERRO: upstream inesperado"; exit 1; }
for t in cmake ninja clang clang++ llvm-config; do command -v "$t" >/dev/null || { echo "ERRO: falta $t"; exit 1; }; done
# Termux is Android, but it is not an NDK cross-build. Patch only an isolated
# source copy for the native tool, never the already-built Android runtime.
NATIVE_SRC="$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX-termux-aot-source"
if [ ! -f "$NATIVE_SRC/.lasrecomp-termux-aot-ready" ]; then
  mkdir -p "$NATIVE_SRC"
  cp -a "$SRC/." "$NATIVE_SRC/"
  python3 - "$NATIVE_SRC/cmake/openssl.cmake" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text()
needle='if(ANDROID)\n    if(ANDROID_ABI STREQUAL "arm64-v8a")'
assert needle in s, "OpenSSL CMake upstream changed"
s=s.replace(needle, 'if(ANDROID AND NOT SNX_TERMUX_NATIVE_AOT)\n    if(ANDROID_ABI STREQUAL "arm64-v8a")',1)
needle2='if(ANDROID)\n    list(APPEND snx_openssl_args -D__ANDROID_API__='
assert needle2 in s
s=s.replace(needle2,'if(ANDROID AND NOT SNX_TERMUX_NATIVE_AOT)\n    list(APPEND snx_openssl_args -D__ANDROID_API__=',1)
p.write_text(s)
PY
  touch "$NATIVE_SRC/.lasrecomp-termux-aot-ready"
fi
# The Android runtime source contains a custom linker block with JNI_OnLoad,
# NDK libc, and diagnostic map flags. Those must not reach a Termux executable.
python3 - "$NATIVE_SRC/src/multicall/CMakeLists.txt" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
begin='    # BEGIN LASRECOMP_ANDROID_2026_LINK\n'
end='    # END LASRECOMP_ANDROID_2026_LINK\n'
if begin in s or end in s:
    if s.count(begin)!=1 or s.count(end)!=1: raise SystemExit('ERRO: bloco de linker invalido')
    left,rest=s.split(begin,1)
    _,right=rest.split(end,1)
    p.write_text(left+right)
PY
# Build the multicall CLI as an executable in Termux (not libscarletnx.so).
python3 - "$NATIVE_SRC/src/multicall/CMakeLists.txt" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old='if(ANDROID)\n    # the app (dist/android): its game activity loads libscarletnx.so'
new='if(ANDROID AND NOT SNX_TERMUX_NATIVE_AOT)\n    # the app (dist/android): its game activity loads libscarletnx.so'
if old in s: p.write_text(s.replace(old,new,1))
elif new not in s: raise SystemExit('ERRO: alvo multicall mudou')
PY
# Native Termux has ANDROID=true in CMake, but no NDK target/sysroot.
# Fix only the native AOT copy; preserve Android runtime source untouched.
python3 - "$NATIVE_SRC/src/common/cpu/recompiler/llvm/CMakeLists.txt" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old='if(ANDROID)\n    set(snx_rtlib_flags --target=${CMAKE_C_COMPILER_TARGET} --sysroot=${CMAKE_SYSROOT})'
new='if(ANDROID AND NOT SNX_TERMUX_NATIVE_AOT)\n    set(snx_rtlib_flags --target=${CMAKE_C_COMPILER_TARGET} --sysroot=${CMAKE_SYSROOT})'
if old in s: p.write_text(s.replace(old,new,1))
elif new not in s: raise SystemExit('ERRO: rtlib CMake alterado no upstream')
PY
# CMake cannot change an existing target from SHARED to EXECUTABLE in place:
# use a new native CLI build tree once, leaving previous compiled artifacts safe.
BUILD="$HOME/.cache/lasrecomp-scarletnx-upgrade/termux-aot-cli-2026"
mkdir -p "$BUILD"
echo "=== CONFIGURANDO GERADOR NATIVO TERMUX (SEM NDK) ==="
cmake -S "$NATIVE_SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_C_COMPILER="$PREFIX/bin/clang" \
  -DCMAKE_CXX_COMPILER="$PREFIX/bin/clang++" \
  -DSNX_TERMUX_NATIVE_AOT=ON -DSNX_TOOLS_ONLY=ON -DSNX_BUILD_NX=ON \
  -DSNX_BUILD_GNUABI=OFF -DSNX_BUILD_3DS=OFF \
  -DSNX_BUILD_VITA=OFF -DSNX_BUILD_AGB=OFF \
  -DSNX_BUILD_GUI=OFF -DSNX_DEPLOY=OFF \
  -DSNX_BUILD_TESTING=OFF -DBUILD_TESTING=OFF \
  -DCMAKE_BUILD_TYPE=Release -DLLVM_DIR="$PREFIX/lib/cmake/llvm" \
  -DSNX_TERMUX_NATIVE_LLVM=ON -DSNX_LLVM_CONFIG="$PREFIX/bin/llvm-config"
echo "=== COMPILANDO SOMENTE EXECUTAVEL AOT ==="
cmake --build "$BUILD" --target scarletnx --parallel "${SCARLETNX_BUILD_JOBS:-2}"
BIN="$BUILD/scarletnx"
[ -x "$BIN" ] || { echo "ERRO: executavel ausente"; exit 1; }
file "$BIN"
echo "TERMUX_AOT_TOOL_READY=$BIN"
echo "Proxima etapa: validar argumentos e recompilar Zelda em diretorio privado."
