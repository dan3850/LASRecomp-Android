#!/data/data/com.termux/files/usr/bin/bash
# Inspect the actual ScarletNX 2026 AOT producer before attempting Zelda recompilation.
# Read-only, safe for the existing runtime and stable APK.
set -euo pipefail
BASE="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="${SCARLETNX_UPGRADE_SOURCE:-$BASE/ScarletNX}"
BUILD="$BASE/android-arm64-build-2026"
ROM='/storage/emulated/0/Emuladores Roms/Nintendo Switch/The Legend of Zelda Link'\''s Awakening [01006BB00C6F0000] [v131072] (1G+1U).xci'
EXTRACTED='/storage/emulated/0/SwitchRoms/Zelda-extraido'
[ -d "$SRC/.git" ] || { echo "ERRO: checkout ScarletNX ausente"; exit 1; }
[ "$(git -C "$SRC" rev-parse HEAD)" = 05324b57629d0894506b31beb2c72869138b7ad1 ] || { echo "ERRO: revisao inesperada"; exit 1; }
echo "=== ORIGENS DO ZELDA ==="
for f in "$ROM" "$EXTRACTED/exefs/main" "$EXTRACTED/exefs/sdk" "$EXTRACTED/romfs/region_common"; do
  if [ -e "$f" ]; then ls -ldh "$f"; else echo "AUSENTE: $f"; fi
done
echo "=== FERRAMENTAS AOT DISPONIVEIS ==="
for f in "$BUILD"/scarletnx "$BUILD"/src/multicall/scarletnx "$BUILD"/src/aot/* "$BUILD"/tools/*; do
  [ -f "$f" ] || continue
  file "$f" 2>/dev/null || ls -lh "$f"
done
echo "=== DECLARACOES DE AOT NO UPSTREAM ==="
grep -RInE --include='*.c' --include='*.cpp' --include='*.h' --include='CMakeLists.txt' --include='*.md' \
  -m 3 'snx_module|SNX_ABI|_code\\.so|aot_compile|AOT.*compile|compile.*AOT' \
  "$SRC/src" "$SRC/docs" "$SRC/README.md" 2>/dev/null | head -100 || true
echo "=== OBSERVACAO ==="
echo "A biblioteca libscarletnx.so Android nao deve ser executada como CLI Termux sem confirmar um entrypoint."
echo "Nenhum AOT foi gerado; use as declaracoes acima para identificar a interface correta."
