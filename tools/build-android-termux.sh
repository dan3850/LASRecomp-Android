#!/usr/bin/env bash
# Build an actual installable Android APK (arm64-v8a) from the APK's native source.
# Works natively in Termux arm64 or with the Android NDK cross compiler in CI.
# This script is a build tool; neither Termux nor a shell is required to run the APK.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/android-bootstrap"
APP="$ROOT/android/bootstrap"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$PREFIX/opt/android-sdk}}"
KEYSTORE="${ANDROID_DEBUG_KEYSTORE:-$HOME/.lasrecomp-android-debug.keystore}"
CC_BIN="${ANDROID_CC:-clang}"
AAPT2_BIN="${ANDROID_AAPT2:-aapt2}"
ZIPALIGN_BIN="${ANDROID_ZIPALIGN:-zipalign}"
APKSIGNER_BIN="${ANDROID_APKSIGNER:-apksigner}"
D8_BIN="${ANDROID_D8:-$(dirname "$(command -v "$AAPT2_BIN" 2>/dev/null || echo "$AAPT2_BIN")")/d8}"
if [[ ! -x "$D8_BIN" ]] && command -v d8 >/dev/null 2>&1; then D8_BIN=d8; fi

if [[ "$(uname -m)" != "aarch64" && -z "${ANDROID_CC:-}" ]]; then
    echo "ERRO: em hosts nao-ARM64 configure ANDROID_CC com o compilador do Android NDK" >&2
    exit 1
fi

for cmd in "$CC_BIN" "$AAPT2_BIN" "$ZIPALIGN_BIN" "$APKSIGNER_BIN" "$D8_BIN" zip javac jar keytool; do
    if ! command -v "$cmd" >/dev/null 2>&1 && [[ ! -x "$cmd" ]]; then
        echo "ERRO: ferramenta de build nao encontrada: $cmd" >&2
        exit 1
    fi
done

if [[ -z "${ANDROID_JAR:-}" ]]; then
    if [[ ! -d "$ANDROID_HOME/platforms" ]]; then
        echo "ERRO: SDK Platform Android nao encontrada em $ANDROID_HOME/platforms" >&2
        exit 1
    fi
    ANDROID_JAR="$(find "$ANDROID_HOME/platforms" -name android.jar -type f | sort -V | tail -n 1)"
fi
if [[ ! -f "${ANDROID_JAR:-}" ]]; then
    echo "ERRO: android.jar nao encontrado. Defina ANDROID_JAR" >&2
    exit 1
fi

mkdir -p "$OUT/lib/arm64-v8a"
LIB="$OUT/lib/arm64-v8a/liblasrecomp_bootstrap.so"
APK="$OUT/LASRecomp-Android.apk"
echo "[1/5] Compilando biblioteca Android ARM64 para o APK"
"$CC_BIN" -fPIC -shared -O2 -g -fvisibility=hidden \
    -Wl,-z,max-page-size=16384 -Wl,-soname,liblasrecomp_bootstrap.so \
    -o "$LIB" "$APP/bootstrap.c" -landroid -llog -ldl
echo "[1/5] Compilando o preparador real de RomFS dentro do APK"
"$CC_BIN" -fPIC -shared -O2 -fvisibility=hidden \
    -Wl,-z,max-page-size=16384 -Wl,-soname,liblasrecomp_prepare.so \
    -o "$OUT/lib/arm64-v8a/liblasrecomp_prepare.so" \
    "$ROOT/android/prepare/game_prepare.c" "$ROOT/runtime/romfs_build.c" -llog

echo "[2/5] Compilando Activity real de importacao do jogo"
mkdir -p "$OUT/java-classes" "$OUT/dex"
javac -source 8 -target 8 -encoding UTF-8 -classpath "$ANDROID_JAR" \
    -d "$OUT/java-classes" \
    "$ROOT/android/src/com/retroaura/lasrecomp/GameImportActivity.java"
jar cf "$OUT/app-classes.jar" -C "$OUT/java-classes" .
"$D8_BIN" --min-api 26 --lib "$ANDROID_JAR" --output "$OUT/dex" "$OUT/app-classes.jar"
test -s "$OUT/dex/classes.dex"
echo "[2/5] Montando APK com Activity, AndroidManifest e biblioteca nativa"
rm -f "$OUT/unsigned.apk" "$OUT/aligned.apk" "$APK"
"$AAPT2_BIN" link -I "$ANDROID_JAR" --manifest "$APP/AndroidManifest.xml" \
    -o "$OUT/unsigned.apk"
# SDL3 is a real dependency of the game runtime, not a Vulkan diagnostic.
# CI builds it with the Android NDK; local packaging can supply the same ARM64 .so.
NATIVE_LIBS=(lib/arm64-v8a/liblasrecomp_bootstrap.so lib/arm64-v8a/liblasrecomp_prepare.so)
if [[ -n "${SDL3_ANDROID_SO:-}" ]]; then
    [[ -s "$SDL3_ANDROID_SO" ]] || { echo "ERRO: SDL3_ANDROID_SO invalido" >&2; exit 1; }
    cp "$SDL3_ANDROID_SO" "$OUT/lib/arm64-v8a/libSDL3.so"
    NATIVE_LIBS+=(lib/arm64-v8a/libSDL3.so)
fi
(cd "$OUT" && zip -q unsigned.apk "${NATIVE_LIBS[@]}")
(cd "$OUT/dex" && zip -q "$OUT/unsigned.apk" classes.dex)
"$ZIPALIGN_BIN" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "[3/5] Preparando assinatura debug local"
mkdir -p "$(dirname "$KEYSTORE")"
if [[ ! -f "$KEYSTORE" ]]; then
    keytool -genkeypair -noprompt \
        -keystore "$KEYSTORE" -storepass android -keypass android \
        -alias androiddebugkey -keyalg RSA -keysize 2048 \
        -validity 10000 -dname "CN=LASRecomp Android Debug,O=RetroAura,C=BR"
    chmod 600 "$KEYSTORE"
fi

echo "[4/5] Assinando APK Android"
"$APKSIGNER_BIN" sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
    --ks-pass pass:android --key-pass pass:android \
    --out "$APK" "$OUT/aligned.apk"

echo "[5/5] Verificando APK assinado"
"$APKSIGNER_BIN" verify "$APK"
echo "APK INSTALAVEL: $APK"
echo "OBS: importacao exefs/romfs, validacao v1.0.0 e preparo de romfs.bin no APK. Jogo ainda nao habilitado."
