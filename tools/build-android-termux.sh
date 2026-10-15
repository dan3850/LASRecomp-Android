#!/data/data/com.termux/files/usr/bin/bash
# Build the phase-1 native Android APK entirely inside arm64 Termux.
# Does not run Gradle, depend on x86_64 host tools, or compile LASRecomp game code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/android-bootstrap"
APP="$ROOT/android/bootstrap"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$PREFIX/opt/android-sdk}}"
KEYSTORE="$HOME/.lasrecomp-android-debug.keystore"

if [[ "$(uname -m)" != "aarch64" ]]; then
    echo "ERRO: este script precisa de Termux arm64 (aarch64)." >&2
    exit 1
fi

for cmd in clang aapt2 zip zipalign apksigner keytool; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERRO: faltando $cmd. Veja docs/android-termux.md" >&2
        exit 1
    fi
done

if [[ -z "${ANDROID_JAR:-}" ]]; then
    if [[ ! -d "$ANDROID_HOME/platforms" ]]; then
        echo "ERRO: falta o SDK Platform Android. ANDROID_HOME=$ANDROID_HOME" >&2
        echo 'Instale uma plataforma SDK, por exemplo: sdkmanager "platforms;android-35"' >&2
        exit 1
    fi
    ANDROID_JAR="$(find "$ANDROID_HOME/platforms" -name android.jar -type f | sort -V | tail -n 1)"
fi
if [[ ! -f "${ANDROID_JAR:-}" ]]; then
    echo "ERRO: android.jar nao encontrado. Defina ANDROID_JAR=/caminho/android.jar" >&2
    exit 1
fi

mkdir -p "$OUT/lib/arm64-v8a"
LIB="$OUT/lib/arm64-v8a/liblasrecomp_bootstrap.so"
APK="$OUT/LASRecomp-Android-phase1.apk"
echo "[1/5] Compilando biblioteca ARM64 nativa (sem codigo do jogo)"
clang -fPIC -shared -O2 -g -fvisibility=hidden \
    -Wl,-z,max-page-size=16384 \
    -Wl,-soname,liblasrecomp_bootstrap.so \
    -o "$LIB" "$APP/bootstrap.c" -landroid -llog -ldl

echo "[2/5] Criando APK com aapt2 nativo do Termux"
rm -f "$OUT/unsigned.apk" "$OUT/aligned.apk"
aapt2 link -I "$ANDROID_JAR" --manifest "$APP/AndroidManifest.xml" \
    -o "$OUT/unsigned.apk"

echo "[3/5] Incluindo a biblioteca native activity"
(
    cd "$OUT"
    zip -q unsigned.apk lib/arm64-v8a/liblasrecomp_bootstrap.so
)
zipalign -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "[4/5] Assinando APK de teste"
if [[ ! -f "$KEYSTORE" ]]; then
    keytool -genkeypair -noprompt \
        -keystore "$KEYSTORE" -storepass android -keypass android \
        -alias androiddebugkey -keyalg RSA -keysize 2048 \
        -validity 10000 -dname "CN=LASRecomp Android Debug,O=RetroAura,C=BR"
    chmod 600 "$KEYSTORE"
fi
apksigner sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
    --ks-pass pass:android --key-pass pass:android \
    --out "$APK" "$OUT/aligned.apk"

echo "[5/5] Verificando assinatura"
apksigner verify "$APK"
echo "APK GERADO: $APK"
echo "Teste: instale o APK; tela 'ARM64 BOOTSTRAP' = NativeActivity carregada."
echo "Logs: logcat -d -s LASRecompAndroid:I AndroidRuntime:E"
