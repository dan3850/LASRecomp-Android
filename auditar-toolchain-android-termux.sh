#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
DEST="$HOME/storage/downloads/ScarletNX-auditoria-ndk.txt"
mkdir -p "$(dirname "$DEST")"
{
echo "SCARLETNX_NDK_AUDIT"
echo "=== NDK INSTALLATIONS ==="
find "$HOME/android-sdk/ndk" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null || true
echo "=== CANDIDATE DRIVERS ==="
for ndk in "$HOME"/android-sdk/ndk/*; do
  [[ -d "$ndk" ]] || continue
  echo "--- $ndk"
  for exe in "$ndk/toolchains/llvm/prebuilt/bin/clang++" "$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/clang++" "$ndk/toolchains/llvm/prebuilt/linux-aarch64/bin/clang++"; do
    [[ -e "$exe" ]] || continue
    ls -l "$exe"
    file "$exe" || true
    head -c 100 "$exe" | strings | head -3 || true
    echo "DRIVER TRACE:"
    "$exe" --target=aarch64-none-linux-android24 -shared -### -x c++ /dev/null -o /dev/null 2>&1 | grep -E 'clang-21|ld[.]lld|crtbegin_so[.]o|sysroot|libc[+]+' | tail -12 || true
  done
done
echo "=== NDK COMPILER WRAPPERS ==="
find "$HOME/android-sdk/ndk" -path '*/prebuilt/bin/clang++' -type f -exec grep -l '/data/data/com.termux' {} \; 2>/dev/null || true
echo "=== AVAILABLE LINKERS ==="
command -v ld.lld || true
echo "=== ENV ==="
printf 'CC=%s\nCXX=%s\nANDROID_NDK_ROOT=%s\n' "${CC:-}" "${CXX:-}" "${ANDROID_NDK_ROOT:-}"
} > "$DEST" 2>&1
echo "RELATORIO_GERADO=$DEST"
