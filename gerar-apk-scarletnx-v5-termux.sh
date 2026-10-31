#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
OUT="$ROOT/scarletnx-android-apk-2026"
BUILD="$OUT/arm64-v8a"
SRC="$ROOT/ScarletNX"
NDK="$HOME/android-sdk/ndk/28.2.13676358"
NATIVE="$BUILD/src/gui/libmain.so"
STAGE="$OUT/stage/lib/arm64-v8a"
APK="$OUT/stage/gradle/outputs/apk/debug/ScarletNX-debug.apk"
REPORT="$HOME/storage/downloads/ScarletNX-apk-v5-build.txt"
mkdir -p "$HOME/storage/downloads"
[[ -s "$NATIVE" && -d "$STAGE" ]] || { echo "ERRO: build nativa ou stage ausente"; exit 2; }
if [[ ! -s "$BUILD/scarletnx-relink-v5.sh" ]]; then
  echo "ERRO: rode relink-scarletnx-ndk-v5-termux.sh antes para gerar o comando v5"; exit 2
fi
if [[ -z "${GRADLE:-}" ]]; then
  GRADLE="$(command -v gradle || true)"
fi
[[ -n "${GRADLE:-}" ]] || { echo "ERRO: Gradle ausente; defina GRADLE=/caminho/gradle"; exit 2; }
BACKUP="$NATIVE.pre-apk-v5"
cp -f "$NATIVE" "$BACKUP"
success=0
restore_on_error() {
  if [[ "$success" != 1 ]]; then
    cp -f "$BACKUP" "$NATIVE"
    echo "ORIGINAL_NATIVE_RESTORED_AFTER_ERROR" >> "$REPORT"
  fi
}
trap restore_on_error EXIT
{
echo SCARLETNX_APK_V5_BUILD
echo '=== RELINK NDK ==='
(cd "$BUILD" && sh scarletnx-relink-v5.sh)
echo '=== VERIFY ELF ==='
readelf -d "$NATIVE" | grep NEEDED
readelf -d "$NATIVE" | grep -q 'NEEDED.*libc[.]so' || { echo 'FAIL: missing dynamic libc'; exit 3; }
if readelf -Ws "$NATIVE" | awk '$7 != "UND" && ($8=="getauxval" || $8=="__libc_init") {bad=1} END {exit !bad}'; then
 echo 'FAIL: embedded bionic symbols'; exit 3
fi
echo 'NATIVE_DYNAMIC_LIBC_OK'
echo '=== STAGE NATIVE ==='
install -m 644 "$NATIVE" "$STAGE/libmain.so"
CXX="$NDK/toolchains/llvm/prebuilt/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"
[[ -s "$CXX" ]] || { echo 'FAIL: missing libc++_shared'; exit 3; }
install -m 644 "$CXX" "$STAGE/libc++_shared.so"
echo '=== GRADLE APK ==='
"$GRADLE" -p "$SRC/dist/android" --project-cache-dir "$OUT/gradle-cache" assembleDebug "-Pscarletnx.stage=$OUT/stage"
[[ -s "$APK" ]] || { echo 'FAIL: apk missing'; exit 3; }
unzip -Z1 "$APK" | grep -qx 'lib/arm64-v8a/libmain.so' || { echo 'FAIL: libmain missing from apk'; exit 3; }
unzip -Z1 "$APK" | grep -qx 'lib/arm64-v8a/libc++_shared.so' || { echo 'FAIL: libc++ missing from apk'; exit 3; }
cp -f "$APK" "$HOME/storage/downloads/ScarletNX-debug.apk"
sha256sum "$HOME/storage/downloads/ScarletNX-debug.apk"
echo 'APK_V5_READY'
} > "$REPORT" 2>&1
success=1
echo "APK_DOWNLOAD=$HOME/storage/downloads/ScarletNX-debug.apk"
echo "REPORT_DOWNLOAD=$REPORT"
