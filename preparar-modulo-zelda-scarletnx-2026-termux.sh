#!/data/data/com.termux/files/usr/bin/bash
# Stage a PRIVATE ScarletNX ABI-12 Zelda AOT module for Android.
# This never compiles or publishes game-derived code.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.cache/lasrecomp-scarletnx-upgrade/output"
SOURCE="${1:-${ZELDA_SNX_AOT_SO:-}}"
if [ -z "$SOURCE" ]; then
  echo "ERRO: informe o caminho do modulo Zelda AOT gerado pelo ScarletNX 2026."
  echo "Uso: bash preparar-modulo-zelda-scarletnx-2026-termux.sh /caminho/libzelda_snx.so"
  echo "IMPORTANTE: liblasgame.so antiga nao e um modulo ScarletNX ABI 12."
  exit 2
fi
[ -s "$SOURCE" ] || { echo "ERRO: modulo ausente: $SOURCE"; exit 1; }
for tool in readelf nm patchelf; do command -v "$tool" >/dev/null || { echo "ERRO: falta $tool"; exit 1; }; done
readelf -h "$SOURCE" | grep -q AArch64 || { echo "ERRO: modulo nao e AArch64"; exit 1; }
if ! nm -D --defined-only "$SOURCE" | grep -Eq '[[:space:]]snx_module$'; then
  echo "ERRO: modulo nao exporta snx_module; nao e compativel com o carregador ScarletNX."
  exit 1
fi
DEST="$BASE/android-ready/arm64-v8a"
[ -s "$DEST/libscarletnx.so" ] || { echo "ERRO: prepare primeiro as bibliotecas Android"; exit 1; }
TMP="$DEST/libzelda_snx.so.tmp"
cp -L "$SOURCE" "$TMP"
patchelf --set-soname libzelda_snx.so "$TMP"
patchelf --remove-rpath "$TMP"
# No arbitrary external dependencies allowed in the private game module.
while IFS= read -r needed; do
  [ -z "$needed" ] && continue
  case "$needed" in
    libc.so|libm.so|libdl.so|liblog.so|libandroid.so|libz.so|libvulkan.so|libEGL.so|libGLESv1_CM.so|libGLESv2.so|libOpenSLES.so) ;;
    *) [ -s "$DEST/$needed" ] || { echo "ERRO: dependencia nao empacotada: $needed"; rm -f "$TMP"; exit 1; } ;;
  esac
done < <(readelf -d "$TMP" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p')
mv -f "$TMP" "$DEST/libzelda_snx.so"
echo "ZELDA_SNX_AOT_STAGED=$DEST/libzelda_snx.so"
echo "SIMBOLO snx_module presente; ABI numerica e execucao ainda exigem validacao no Android."
echo "APK_ZELDA_2026_READY=NO (launcher Android ainda nao integrado)"
