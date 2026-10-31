#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
B="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
DEST="$HOME/storage/downloads/ScarletNX-linker-real.txt"
mkdir -p "$(dirname "$DEST")"
{
echo "SCARLETNX_LINKER_REAL"
echo "=== MAIN CMAKE CACHE ==="
grep -E '^(CMAKE_(C|CXX)_COMPILER|CMAKE_(C|CXX)_FLAGS|CMAKE_SHARED_LINKER_FLAGS|CMAKE_SYSROOT|ANDROID_NDK|CMAKE_TOOLCHAIN_FILE|CMAKE_(C|CXX)_STANDARD_LIBRARIES)' "$B/CMakeCache.txt" || true
echo "=== LINK RULE FOR LIBMAIN ==="
if [[ -f "$B/build.ninja" ]]; then
 grep -n -m 12 -E 'libmain[.]so|LINKER__main|LINKER__.*Release|LINKER__.*Debug' "$B/build.ninja" || true
 echo "=== NINJA COMMANDS LINKING LIBMAIN ==="
 ninja -C "$B" -t commands 2>&1 | grep -E '(-o |/)(libmain[.]so)( |$)' | tail -5 | cut -c 1-12000 || true
fi
echo "=== CMAKE LINK TEXT ==="
find "$B" -name link.txt -type f -print | head -20
echo "=== COMPILER DRIVER TRACE ==="
NDK="$HOME/android-sdk/ndk/28.2.13676358"
for cc in "$NDK/toolchains/llvm/prebuilt/bin/clang++" "$PREFIX/bin/clang++"; do
 if [[ -x "$cc" ]]; then
 echo "--- $cc"
 "$cc" --target=aarch64-none-linux-android24 -shared -### -x c++ /dev/null -o /dev/null 2>&1 | grep -E 'ld.lld|crtbegin|crtend|libc|sysroot|/usr/lib' | tail -8 || true
 fi
done
} > "$DEST" 2>&1
echo "RELATORIO_GERADO=$DEST"
