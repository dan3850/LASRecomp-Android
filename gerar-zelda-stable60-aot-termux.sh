#!/data/data/com.termux/files/usr/bin/bash
# Generate a NEW Zelda AOT with a runtime-switchable two-BL patch.
# Usage: bash gerar-zelda-stable60-aot-termux.sh /absolute/path/to/game.xci-or-extracted
# Never recompiles into or overwrites the original known-booting code.so.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests -p 'test_scarletnx_zelda60_toggle.py'
test "$(git branch --show-current)" = "experimental/zelda-links-awakening-ryujinx-nativeaot" || {
  echo "ERRO: branch Zelda experimental obrigatoria" >&2
  exit 1
}
test "$#" = 1 || {
  echo "Uso: bash gerar-zelda-stable60-aot-termux.sh /caminho/Zelda.xci" >&2
  echo "Tambem aceita pasta extraida que contenha exefs/main." >&2
  exit 2
}
INPUT="$1"
if [ -d "$INPUT" ]; then
  test -s "$INPUT/exefs/main" && test -s "$INPUT/exefs/main.npdm" || {
    echo "ERRO: extracao invalida; faltam exefs/main ou exefs/main.npdm" >&2
    exit 2
  }
elif [ -f "$INPUT" ]; then
  case "${INPUT,,}" in
    *.xci|*.xcz|*.nsp|*.nsz|*.dnsp|*.dxci) ;;
    *) echo "ERRO: arquivo nao parece um dump Switch suportado" >&2; exit 2 ;;
  esac
else
  echo "ERRO: entrada nao encontrada: $INPUT" >&2
  exit 2
fi
for tool in cmake ninja python3 llvm-readelf git; do
  command -v "$tool" >/dev/null || { echo "ERRO: ferramenta ausente: $tool" >&2; exit 1; }
done
BASE="$HOME/.cache/lasrecomp-scarletnx-romfs"
SRC="$BASE/ScarletNX"
BUILD="$BASE/zelda60-aot-tools-android26-build"
GAME="01006BB00C6F0000"
OUTDIR="/storage/emulated/0/Download/ZeldaRecomp/Stable60AOT"
DEST="$OUTDIR/${GAME}_code.so"
test -s "$SRC/src/nx/loader/module_llvm.c" || {
  echo "ERRO: fonte ScarletNX cache ausente" >&2
  exit 1
}
PINNED="34853eeae5af132e320adbb0193f13344085bf89"
test "$(git -C "$SRC" rev-parse HEAD)" = "$PINNED" || {
  echo "ERRO: ScarletNX diferente de 34853ee. ABI 12 deve ser preservada." >&2
  exit 1
}
JOBS="${SCARLETNX_BUILD_JOBS:-2}"
PATCH="$ROOT/tools/patch_scarletnx_zelda60_toggle.py"
python3 "$PATCH" "$SRC" --mode aot --check
restore_source() {
  local status="$?"
  trap - EXIT
  python3 "$PATCH" "$SRC" --mode aot --revert || {
    echo "ERRO: nao consegui restaurar o cache de fontes ScarletNX" >&2
    exit 1
  }
  exit "$status"
}
trap restore_source EXIT
python3 "$PATCH" "$SRC" --mode aot
mkdir -p "$OUTDIR"
echo "===== CONFERINDO TOOLCHAIN ANDROID ARM64 DO TERMUX ====="
# The tools-only executable still uses Android's NDK sysroot and OpenSSL's
# Android target. Without ANDROID_ABI the OpenSSL CMake configuration aborts.
if [ -z "${ANDROID_NDK_ROOT:-}" ]; then
  for candidate in "${ANDROID_HOME:-$HOME/Android/Sdk}"/ndk/* "$HOME/android-sdk/ndk/"*; do
    if [ -f "$candidate/build/cmake/android.toolchain.cmake" ]; then
      ANDROID_NDK_ROOT="$candidate"
    fi
  done
fi
export ANDROID_NDK_ROOT="${ANDROID_NDK_ROOT:-}"
[ -f "$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" ] || {
  echo "ERRO: NDK nao encontrado. Configure ANDROID_NDK_ROOT para o NDK r28c." >&2
  exit 1
}
export ANDROID_NDK_HOME="$ANDROID_NDK_ROOT"
NDK_API_LIB="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot/usr/lib/aarch64-linux-android/26"
[ -s "$NDK_API_LIB/libc.so" ] || {
  echo "ERRO: biblioteca de importacao libc Android 26 ausente" >&2
  exit 1
}
CXX_RUNTIME="$PREFIX/lib/libc++_shared.so"
[ -s "$CXX_RUNTIME" ] || {
  echo "ERRO: biblioteca C++ compartilhada do Termux ausente: $CXX_RUNTIME" >&2
  exit 1
}
[ -x "$PREFIX/bin/llvm-config" ] || {
  echo "ERRO: llvm-config do Termux nao encontrado" >&2
  exit 1
}
# The existing ARM64 runtime build already uses this private OpenSSL compiler
# alias. Reuse it; regenerate only if it has not been produced yet.
OPENSSL_CC_BIN="$BASE/openssl-cc-bin"
OPENSSL_CC="$OPENSSL_CC_BIN/aarch64-linux-android26-clang"
if [ ! -x "$OPENSSL_CC" ]; then
  mkdir -p "$OPENSSL_CC_BIN"
  printf '#!/data/data/com.termux/files/usr/bin/sh\nexec "%s" --target=aarch64-none-linux-android26 --sysroot="%s" -L"%s" "$@"\n' \
    "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/bin/clang" \
    "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot" "$PREFIX/lib" > "$OPENSSL_CC"
  chmod 755 "$OPENSSL_CC"
fi
export SNX_TERMUX_OPENSSL_BIN="$OPENSSL_CC_BIN"
# The pinned runtime builder already uses the same, reversible-in-principle
# OpenSSL CMake PATH adapter. Avoid editing cached CPM packages or resetting
# existing working Android build directories.
python3 - "$SRC/cmake/openssl.cmake" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
old = '"PATH=${ANDROID_TOOLCHAIN_ROOT}/bin:$ENV{PATH}"'
new = '"PATH=$ENV{SNX_TERMUX_OPENSSL_BIN}:${ANDROID_TOOLCHAIN_ROOT}/bin:$ENV{PATH}"'
text = path.read_text()
if text.count(new) == 1:
    print("ZELDA60_OPENSSL_PATH: reutilizado")
elif text.count(old) == 1:
    path.write_text(text.replace(old, new, 1))
    print("ZELDA60_OPENSSL_PATH: adaptado para Termux")
else:
    raise SystemExit("ERRO: versao inesperada de cmake/openssl.cmake")
PY
export CMAKE_BUILD_PARALLEL_LEVEL="$JOBS"
export MAKEFLAGS="-j$JOBS"
echo "===== COMPILANDO FERRAMENTA AOT COM CACHE NINJA ====="
echo "AOT_TOOLCHAIN: Android ABI arm64-v8a, API 26, NDK $ANDROID_NDK_ROOT"
# A separate build folder avoids mixing the earlier incomplete non-NDK
# CMakeCache with this correctly targeted configuration. Source/CPM caches
# and the already booting ARM64 game library remain unchanged.
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
  -DSNX_TOOLS_ONLY=ON -DSNX_BUILD_NX=ON -DSNX_BUILD_GUI=OFF \
  -DSNX_BUILD_GNUABI=OFF -DSNX_BUILD_3DS=OFF -DBUILD_TESTING=OFF \
  -DSNX_DEPLOY=OFF -DCMAKE_BUILD_TYPE=Release \
  -DSNX_TERMUX_NATIVE_LLVM=ON \
  -DSNX_LLVM_CONFIG="$PREFIX/bin/llvm-config" \
  -DLLVM_DIR="$PREFIX/lib/cmake/llvm" \
  -DCMAKE_EXE_LINKER_FLAGS="-L$NDK_API_LIB -L$PREFIX/lib" \
  -DCMAKE_CXX_FLAGS="-nostdlib++" \
  -DCMAKE_CXX_STANDARD_LIBRARIES="$CXX_RUNTIME" \
  -DCMAKE_SHARED_LINKER_FLAGS="-L$NDK_API_LIB -L$PREFIX/lib" \
  -DCMAKE_MODULE_LINKER_FLAGS="-L$NDK_API_LIB -L$PREFIX/lib"
cmake --build "$BUILD" --target scarletnx --parallel "$JOBS"
test -x "$BUILD/scarletnx" || {
  echo "ERRO: executavel AOT nao foi gerado" >&2
  exit 1
}
echo "===== RECOMPILANDO SOMENTE O ZELDA EM PASTA SEPARADA ====="
RUNTIME="${SCARLETNX_RUNTIME_SO:-$HOME/scarletnx-zelda-shader-build/libscarletnx.so}"
test -s "$RUNTIME" || {
  echo "ERRO: runtime ABI 12 ausente para --runtime: $RUNTIME" >&2
  exit 1
}
# ScarletNX's recompiler reads a Switch XCI/NSP directly in place:
# snx_recompile() detects dump input and invokes load_dump(). No extraction,
# cache reset or ROM copy is necessary. ExeFS input also remains supported.
# The explicit '--' keeps the game filename (which contains spaces and
# brackets) separate from recompiler options.
# The Android NDK executable is linked to Termux's shared LLVM but
# NDK's linker does not add a Termux RUNPATH. Resolve libLLVM.so and the
# matching libc++_shared.so from Termux during THIS invocation only.
# Do not relink the tool or modify global linker configuration.
if [ ! -r "$PREFIX/lib/libLLVM.so" ]; then
  echo "ERRO: libLLVM.so nao encontrada em $PREFIX/lib" >&2
  echo "Bibliotecas LLVM disponiveis:" >&2
  ls -l "$PREFIX"/lib/libLLVM* >&2 || true
  exit 1
fi
echo "ZELDA60_LLVM_RUNTIME_PATH: $PREFIX/lib"
LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  SNX_ZELDA60_AOT=1 "$BUILD/scarletnx" -r --outdir "$OUTDIR" \
  --runtime "$RUNTIME" --jobs "$JOBS" -- "$INPUT" "$GAME"
# The driver creates <outdir>/<game>/<game>_code.so.
AOT="$OUTDIR/$GAME/${GAME}_code.so"
test -s "$AOT" || {
  echo "ERRO: AOT nao encontrado em $AOT" >&2
  exit 1
}
llvm-readelf -W --dyn-syms "$AOT" | grep -Fq "snx_zelda_stable60_enabled" || {
  echo "ERRO: AOT nao exportou o toggle; nao substituir a versao antiga" >&2
  exit 1
}
if [ -s "$DEST" ] && ! cmp -s "$AOT" "$DEST"; then
  PREVIOUS="$DEST.previous.$(date +%Y%m%d-%H%M%S)"
  mv "$DEST" "$PREVIOUS"
  echo "AOT experimental anterior preservado: $PREVIOUS"
fi
if [ ! -s "$DEST" ]; then cp -p "$AOT" "$DEST"; fi
echo "===== AOT STABLE60 GERADO E VERIFICADO ====="
echo "$DEST"
echo "Agora: bash compilar-zelda-stable60-toggle-termux.sh"
