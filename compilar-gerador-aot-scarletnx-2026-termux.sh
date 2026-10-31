#!/data/data/com.termux/files/usr/bin/bash
# Native Termux Switch AOT generator, isolated from the Android runtime build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ "$(git -C "$ROOT" branch --show-current)" = android/scarletnx-full-upgrade ] || { echo "ERRO: branch incorreta"; exit 1; }
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
BUILD="$HOME/.cache/lasrecomp-scarletnx-upgrade/termux-aot-tools-2026"
[ "$(git -C "$SRC" rev-parse HEAD)" = 05324b57629d0894506b31beb2c72869138b7ad1 ] || { echo "ERRO: upstream inesperado"; exit 1; }
for t in cmake ninja clang clang++ llvm-config; do command -v "$t" >/dev/null || { echo "ERRO: falta $t"; exit 1; }; done
mkdir -p "$BUILD"
echo "=== CONFIGURANDO GERADOR NATIVO TERMUX (SEM NDK) ==="
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_C_COMPILER="$PREFIX/bin/clang" \
  -DCMAKE_CXX_COMPILER="$PREFIX/bin/clang++" \
  -DSNX_TOOLS_ONLY=ON -DSNX_BUILD_NX=ON \
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
