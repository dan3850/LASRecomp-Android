#!/data/data/com.termux/files/usr/bin/bash
# Audita a integracao Android real do ScarletNX, sem recompilar o Zelda.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="$ROOT/ScarletNX"
GAME="$ROOT/zelda-aot-2026/01006BB00C6F0000"
REPORT="$ROOT/zelda-apk-staging-2026/integracao-android-audit.txt"
[[ -d "$SRC" && -s "$GAME/01006BB00C6F0000_code.so" ]] || { echo "ERRO: fontes ou codigo AOT ausentes"; exit 1; }
mkdir -p "$(dirname "$REPORT")"
{
  echo "=== FONTES ANDROID / GRADLE ==="
  find "$SRC/dist/android" -maxdepth 8 -type f \( -name 'AndroidManifest.xml' -o -name 'build.gradle' -o -name 'build.gradle.kts' -o -name '*.java' -o -name '*.kt' -o -name 'CMakeLists.txt' \) 2>/dev/null | head -100 || true
  echo "=== ENTRADAS NATIVAS / JNI ==="
  rg -n --max-count 5 'System.loadLibrary|JNI_OnLoad|native.*[Mm]ain|scarletnx\.so|scarletnx-run|nativeLibraryDir|dlopen\(' "$SRC/dist/android" "$SRC/src/multicall" "$SRC/src/nx" 2>/dev/null | head -110 || true
  echo "=== DEPENDENCIAS E SONAME ==="
  for f in "$GAME/01006BB00C6F0000" "$GAME/01006BB00C6F0000_code.so" "$PREFIX/lib/libLLVM.so" "$PREFIX/lib/libc++_shared.so"; do
    if [[ -f "$f" ]]; then
      echo "--- $f"
      readelf -d "$f" | grep -E 'NEEDED|SONAME|RPATH|RUNPATH' || true
    fi
  done
  echo "=== ARQUIVOS DE JOGO ==="
  find "$GAME" -maxdepth 2 -type f -printf '%P %s bytes\n' | head -25
} > "$REPORT"
echo "RELATORIO=$REPORT"
cat "$REPORT"
