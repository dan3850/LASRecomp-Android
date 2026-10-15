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
APK="$OUT/LASRecomp-Android.apk"
echo "[1/5] Compilando preparacao real de RomFS dentro do APK"
"$CC_BIN" -fPIC -shared -O2 -fvisibility=hidden \
    -Wl,-z,max-page-size=16384 -Wl,-soname,liblasrecomp_prepare.so \
    -o "$OUT/lib/arm64-v8a/liblasrecomp_prepare.so" \
    "$ROOT/android/prepare/game_prepare.c" "$ROOT/android/prepare/local_code_probe.c" \
    "$ROOT/runtime/romfs_build.c" -llog -ldl

# Tiny, harmless module packaged with the APK. The diagnostic copies it to
# app-private read-only storage to check if on-device .so loading is allowed.
"$CC_BIN" -fPIC -shared -O2 -fvisibility=hidden \
    -Wl,-z,max-page-size=16384 -Wl,-soname,liblasrecomp_probe.so \
    -o "$OUT/lib/arm64-v8a/liblasrecomp_probe.so" \
    "$ROOT/android/prepare/loader_probe_module.c"

echo "[2/5] Preparando Activity Android e ciclo de vida SDL3"
mkdir -p "$OUT/java-classes" "$OUT/dex"
JAVA_SOURCES=("$ROOT/android/src/com/retroaura/lasrecomp/GameImportActivity.java")
NATIVE_LIBS=(lib/arm64-v8a/liblasrecomp_prepare.so lib/arm64-v8a/liblasrecomp_probe.so)

# The SDL3 .so, its official Java integration and the game's SDL_main bridge
# are one inseparable target. We never package an unlaunchable SDLActivity.
if [[ -n "${SDL3_ANDROID_SO:-}" || -n "${SDL3_ANDROID_HEADERS:-}" || -n "${SDL3_ANDROID_JAVA_ROOT:-}" ]]; then
    [[ -s "${SDL3_ANDROID_SO:-}" && -d "${SDL3_ANDROID_HEADERS:-}" && -d "${SDL3_ANDROID_JAVA_ROOT:-}" ]] || {
        echo "ERRO: configure SDL3_ANDROID_SO, SDL3_ANDROID_HEADERS e SDL3_ANDROID_JAVA_ROOT juntos" >&2
        exit 1
    }
    cp "$SDL3_ANDROID_SO" "$OUT/lib/arm64-v8a/libSDL3.so"
    "$CC_BIN" -fPIC -shared -O2 -fvisibility=hidden \
        -Wl,-z,max-page-size=16384 -Wl,-soname,libmain.so \
        -I"$SDL3_ANDROID_HEADERS" -L"$(dirname "$SDL3_ANDROID_SO")" \
        -o "$OUT/lib/arm64-v8a/libmain.so" \
        "$ROOT/android/game/game_entry.c" -lSDL3 -ldl -llog
    mapfile -d '' -t SDL_JAVA_SOURCES < <(find "$SDL3_ANDROID_JAVA_ROOT" -name '*.java' -print0)
    (( ${#SDL_JAVA_SOURCES[@]} > 0 )) || { echo "ERRO: fontes Java SDL3 ausentes" >&2; exit 1; }
    JAVA_SOURCES+=("$ROOT/android/src/com/retroaura/lasrecomp/GameSDLActivity.java")
    JAVA_SOURCES+=("${SDL_JAVA_SOURCES[@]}")
    NATIVE_LIBS+=(lib/arm64-v8a/libSDL3.so lib/arm64-v8a/libmain.so)
fi

# Only include the real engine when it was compiled and strictly linked.
# An NDK .so is not a Termux executable: all of these run inside the APK.
if [[ -n "${LASRECOMP_RUNTIME_SO:-}" ]]; then
    [[ -s "$LASRECOMP_RUNTIME_SO" ]] || {
        echo "ERRO: motor LASRecomp Android nao encontrado: $LASRECOMP_RUNTIME_SO" >&2
        exit 1
    }
    [[ -s "${SHADERC_SO:-}" && -d "${FFMPEG_INSTALL_DIR:-}/lib" && -d "${ANDROID_NDK_HOME:-}" ]] || {
        echo "ERRO: dependencias ARM64 de shaderc/FFmpeg/NDK ausentes" >&2
        exit 1
    }
    LIBOUT="$OUT/lib/arm64-v8a"
    READELF="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
    [[ -x "$READELF" ]] || { echo "ERRO: llvm-readelf ausente" >&2; exit 1; }
    cp -L "$LASRECOMP_RUNTIME_SO" "$LIBOUT/liblasrecomp_runtime.so"
    cp -L "$SHADERC_SO" "$LIBOUT/libshaderc_shared.so"
    NATIVE_LIBS+=(lib/arm64-v8a/liblasrecomp_runtime.so lib/arm64-v8a/libshaderc_shared.so)
    for lib in avformat avcodec avutil swscale swresample; do
        file="$FFMPEG_INSTALL_DIR/lib/lib${lib}.so"
        [[ -s "$file" ]] || { echo "ERRO: FFmpeg nao encontrado: $file" >&2; exit 1; }
        cp -L "$file" "$LIBOUT/lib${lib}.so"
        NATIVE_LIBS+=("lib/arm64-v8a/lib${lib}.so")
    done
    CXX_SHARED="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"
    [[ -s "$CXX_SHARED" ]] || { echo "ERRO: libc++_shared.so nao encontrada" >&2; exit 1; }
    cp -L "$CXX_SHARED" "$LIBOUT/libc++_shared.so"
    NATIVE_LIBS+=(lib/arm64-v8a/libc++_shared.so)

    # Opt-in private game-code module built from the owner's game files.
    # Never enable this in public CI or include game assets in this repo.
    # On Android native code must be in the signed APK, not a writable
    # files/extracted/lasgame.so path.
    if [[ -n "${LASRECOMP_GAME_SO:-}" ]]; then
        [[ "${LASRECOMP_PRIVATE_BUILD:-}" == "1" ]] || {
            echo "ERRO: biblioteca do jogo so pode entrar em APK privado (LASRECOMP_PRIVATE_BUILD=1)" >&2
            exit 1
        }
        [[ -s "$LASRECOMP_GAME_SO" ]] || {
            echo "ERRO: biblioteca recompilada do jogo ausente: $LASRECOMP_GAME_SO" >&2
            exit 1
        }
        NM="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-nm"
        "$NM" -D --defined-only "$LASRECOMP_GAME_SO" | grep -Eq '[[:space:]]lasgame_tables$' || {
            echo "ERRO: liblasgame.so nao exporta lasgame_tables" >&2
            exit 1
        }
        cp -L "$LASRECOMP_GAME_SO" "$LIBOUT/liblasgame.so"
        NATIVE_LIBS+=(lib/arm64-v8a/liblasgame.so)
        echo "Codigo recompilado do usuario incluído neste APK privado."
    fi

    # A generated library with a versioned desktop SONAME (e.g. .so.61)
    # cannot be extracted as an Android lib*.so entry; reject it here.
    for soname in "${NATIVE_LIBS[@]}"; do
        so="$OUT/$soname"
        "$READELF" -h "$so" | grep -q "AArch64" || {
            echo "ERRO: biblioteca com ABI diferente de ARM64: $so" >&2
            exit 1
        }
        declared=$("$READELF" -d "$so" | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p' | head -n 1)
        [[ -z "$declared" || "$declared" == "${soname##*/}" ]] || {
            echo "ERRO: SONAME Android invalido em $so: $declared" >&2
            exit 1
        }
    done
    # No Android JNI library may refer to a non-system lib that the APK
    # doesn't contain. This guards FFmpeg's transitive dependencies too.
    for soname in "${NATIVE_LIBS[@]}"; do
        so="$OUT/$soname"
        while IFS= read -r dep; do
            [[ -n "$dep" ]] || continue
            if [[ -s "$LIBOUT/$dep" ]]; then continue; fi
            case "$dep" in
                libc.so|libm.so|libdl.so|liblog.so|libandroid.so|libz.so|libOpenSLES.so|libGLESv1_CM.so|libGLESv2.so)
                    continue ;;
            esac
            echo "ERRO: dependencia nativa ausente no APK: $soname -> $dep" >&2
            exit 1
        done < <("$READELF" -d "$so" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p')
    done
    echo "Biblioteca real LASRecomp e dependencias ARM64 incluidas no APK."
fi

javac -source 8 -target 8 -encoding UTF-8 -classpath "$ANDROID_JAR" \
    -d "$OUT/java-classes" "${JAVA_SOURCES[@]}"
jar cf "$OUT/app-classes.jar" -C "$OUT/java-classes" .
"$D8_BIN" --min-api 26 --lib "$ANDROID_JAR" --output "$OUT/dex" "$OUT/app-classes.jar"
test -s "$OUT/dex/classes.dex"
echo "[2/5] Montando APK com Activity, AndroidManifest e biblioteca nativa"
rm -f "$OUT/unsigned.apk" "$OUT/aligned.apk" "$APK"
"$AAPT2_BIN" link -I "$ANDROID_JAR" --manifest "$APP/AndroidManifest.xml" \
    -o "$OUT/unsigned.apk"
# Bundle the native game entry and SDL3 Java lifecycle in the SAME APK.
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
if [[ -n "${LASRECOMP_GAME_SO:-}" ]]; then
    echo "APK PRIVADO com motor e codigo recompilado do jogo. Boot real ainda precisa ser validado."
elif [[ -n "${LASRECOMP_RUNTIME_SO:-}" ]]; then
    echo "APK com motor completo, mas sem liblasgame.so. Zelda ainda nao inicia."
else
    echo "APK preliminar sem motor de execucao integrado."
fi
