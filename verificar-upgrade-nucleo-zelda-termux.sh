#!/data/data/com.termux/files/usr/bin/bash
# Compara o nucleo ScarletNX do Zelda TESTE com a compilacao nova.
# Somente leitura; nao altera APK, biblioteca, Git ou cache.
set -euo pipefail
BASE="$HOME/.cache/lasrecomp-scarletnx-upgrade"
OUT="$HOME/storage/downloads/ScarletNX-Zelda-integracao-real.txt"
mkdir -p "$(dirname "$OUT")"
{
 echo "SCARLETNX_ZELDA_INTEGRACAO_REAL"
 echo "=== BRANCH / FONTE NOVA ==="
 git -C "$HOME/LASRecomp-Android" branch --show-current || true
 git -C "$BASE/ScarletNX" rev-parse HEAD 2>/dev/null || true
 echo "=== NOVO NUCLEO ==="
 for f in "$BASE/scarletnx-android-apk-2026/arm64-v8a/libscarletnx.so" "$BASE/output/apk-libs/arm64-v8a/libscarletnx.so" "$BASE/output/android-ready/arm64-v8a/libscarletnx.so"; do
  if [ -s "$f" ]; then
   echo "NEW=$f"; sha256sum "$f"
   readelf -d "$f" | grep -E 'NEEDED|SONAME' || true
   readelf -Ws "$f" | grep -E 'JNI_OnLoad|snx_module' | head -8 || true
  fi
 done
 echo "=== APKS ZELDA EXISTENTES ==="
 for apk in /storage/emulated/0/Download/ZeldaRecomp/*.apk; do
  [ -f "$apk" ] || continue
  echo "APK=$apk"; sha256sum "$apk"
  unzip -Z1 "$apk" 2>/dev/null | grep -E '^lib/arm64-v8a/(libscarletnx|libzelda_snx|libSDL3|libc\+\+_shared)\.so$' || true
  if unzip -Z1 "$apk" 2>/dev/null | grep -qx 'lib/arm64-v8a/libscarletnx.so'; then
   unzip -p "$apk" lib/arm64-v8a/libscarletnx.so | sha256sum
  fi
 done
 echo "=== APK NOVA ==="
 apk="$HOME/storage/downloads/ScarletNX-debug.apk"
 if [ -s "$apk" ]; then
  echo "APK=$apk"; sha256sum "$apk"
  unzip -Z1 "$apk" | grep -E '^lib/arm64-v8a/.*\.so$' | head -30 || true
 fi
 echo "=== REFERENCIA DO CARREGADOR ==="
 echo "CastlevaniaSnxBootActivity.startGame -> MarioSnxGameActivity -> SDL getLibraries scarletnx"
 echo "=== CONCLUSAO ==="
 echo "Auditoria concluida. NAO substituir libscarletnx.so sem validar ABI, patches Zelda e dependencias."
} > "$OUT" 2>&1
echo "RELATORIO=$OUT"
tail -n 45 "$OUT"
