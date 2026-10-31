#!/data/data/com.termux/files/usr/bin/bash
# Inspect the already-built ScarletNX native ELF and candidate static archives.
# No build, clean, install, or source modification.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
OUT="$ROOT/scarletnx-android-apk-2026"
ELF="$OUT/stage/lib/arm64-v8a/libmain.so"
DEST="$HOME/storage/downloads/ScarletNX-origem-getauxval.txt"
[[ -f "$ELF" ]] || { echo "Biblioteca ausente: $ELF"; exit 1; }
mkdir -p "$(dirname "$DEST")"
{
  echo "SCARLETNX_GETAUXVAL_ORIGIN"
  date
  echo "=== ELF / BUILD ID ==="
  sha256sum "$ELF"
  readelf -n "$ELF" | grep 'Build ID' || true
  echo "=== FULL SYMBOL TABLE ==="
  readelf -Ws "$ELF" | grep -E 'getauxval|__libc_init' || true
  echo "=== DYNAMIC DEPENDENCIES ==="
  readelf -d "$ELF" | grep NEEDED || true
  echo "=== TOOLCHAIN ==="
  command -v clang || true
  clang --version | head -2 || true
  echo "=== NATIVE BUILD CACHE ==="
  find "$OUT/arm64-v8a" -name CMakeCache.txt -type f -exec grep -H -E 'CMAKE_(C|CXX)_COMPILER:|CMAKE_SYSROOT:|ANDROID_NDK:|CMAKE_TOOLCHAIN_FILE:' {} \; 2>/dev/null | head -60 || true
  echo "=== LINK COMMANDS ==="
  find "$OUT/arm64-v8a" -name link.txt -type f -exec sh -c 'echo "--- $1"; head -c 3500 "$1"; echo' _ {} \; 2>/dev/null | grep -E -C 1 'libmain|libc|clang|crtbegin|--sysroot' | head -110 || true
  echo "=== ARCHIVES DEFINING GETAUXVAL ==="
  find "$OUT/arm64-v8a" "$ROOT/ScarletNX" -type f -name '*.a' -print0 2>/dev/null |
    while IFS= read -r -d '' archive; do
      result="$(nm -A --defined-only "$archive" 2>/dev/null | grep -E '[[:space:]][TtWw][[:space:]]+getauxval$' || true)"
      [[ -z "$result" ]] || printf '%s\n' "$result"
    done
} > "$DEST" 2>&1
echo "RELATORIO_GERADO=$DEST"
