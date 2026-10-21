#!/data/data/com.termux/files/usr/bin/bash
# Separate, genuine ScarletNX CPU/Horizon/Vulkan runtime with a user-built ABI12 AOT .so.
# Never commits Nintendo-derived binaries or changes the existing LASRecomp boot build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
die() { echo "ERRO: $*" >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || die "Termux ARM64 necessario"
[ "$(git branch --show-current)" = android/mario-snx-runtime-boot ] ||
  die "Selecione android/mario-snx-runtime-boot"
for tool in unzip zip llvm-readelf llvm-nm patchelf; do
  command -v "$tool" >/dev/null || die "Falta ferramenta $tool"
done

SNX_CODE="$(printenv MARIO_SNX_CODE_SO || true)"
[ -n "$SNX_CODE" ] || SNX_CODE=/storage/emulated/0/Download/010028600EBDA000/010028600EBDA000_code.so
[ -s "$SNX_CODE" ] || die "Modulo recompilado ausente: $SNX_CODE"
llvm-nm -D --defined-only "$SNX_CODE" | grep -Eq '[[:space:]]snx_module$' ||
  die "Modulo sem snx_module"
ABI_FILE=/storage/emulated/0/Download/010028600EBDA000/010028600EBDA000.abi
[ ! -s "$ABI_FILE" ] || [ "$(cat "$ABI_FILE")" = 12 ] ||
  die "Requer ABI 12"

CACHE="$HOME/.cache/lasrecomp-mario-snx"
mkdir -p "$CACHE"
SNX_APK="$(printenv SCARLETNX_APK || true)"
if [ -z "$SNX_APK" ]; then
  INSTALLED="$(pm path org.scarletnx 2>/dev/null | sed -n 's/^package://p' | head -1 || true)"
  if [ -n "$INSTALLED" ] && [ -r "$INSTALLED" ]; then
    SNX_APK="$INSTALLED"
    echo "Usando ScarletNX original instalado no celular."
  fi
fi
if [ -z "$SNX_APK" ]; then
  for candidate in \
    /storage/emulated/0/Download/ScarletNX-android-universal.apk \
    /storage/emulated/0/Download/ScarletNX.apk; do
    if [ -s "$candidate" ]; then SNX_APK="$candidate"; break; fi
  done
fi
if [ -z "$SNX_APK" ]; then
  SNX_APK="$CACHE/ScarletNX-android-universal.apk"
  if [ ! -s "$SNX_APK" ]; then
    echo "Baixando ScarletNX original (apenas uma vez)..."
    curl -fL --retry 2 -o "$SNX_APK.partial" \
      https://github.com/scarletnx/nightly/releases/latest/download/ScarletNX-android-universal.apk ||
      die "Download falhou; defina SCARLETNX_APK=/caminho/apk-original"
    mv "$SNX_APK.partial" "$SNX_APK"
  fi
fi
[ -r "$SNX_APK" ] || die "ScarletNX APK ilegivel: $SNX_APK"
unzip -Z1 "$SNX_APK" | grep -Fx 'lib/arm64-v8a/libscarletnx.so' >/dev/null ||
  die "APK ScarletNX sem runtime arm64"

CODE="$ROOT/build/private-mario-full-test"
OUT="$ROOT/build/mario-snx-runtime-boot"
BASE="$ROOT/build/mario-android-boot"
[ -s "$CODE/libmario_test.so" ] ||
  die "O jogo original LASRecomp nao existe; nao vamos recompilar blocos."
[ -s "$CODE/build-report.json" ] || die "build-report.json ausente"
GAME="$(printenv MARIO_GAME || true)"
[ -n "$GAME" ] || GAME=/storage/emulated/0/SwitchRoms/Super-extraido
PROFILE="$BASE/profile/mario_profile_config.h"
if [ ! -s "$PROFILE" ] || [ ! -s "$BASE/profile/mario_boot_profile.json" ]; then
  python3 tools/mario_boot_profile.py --report "$CODE/build-report.json" \
    --game "$GAME" --output "$BASE/profile"
fi
python3 tests/test_mario_snx_probe.py
export LASRECOMP_BUILD_OUT="$OUT"
export LASRECOMP_MARIO_PROFILE="$PROFILE"
export LASRECOMP_MANIFEST="$ROOT/android/mario/AndroidManifest.xml"
export LASRECOMP_APK_FILENAME=Mario-SNX-Runtime-BOOT.apk
export LASRECOMP_DOWNLOAD_FOLDER=MarioRecomp
export LASRECOMP_GAME_SO="$CODE/libmario_test.so"
echo "===== PREPARANDO BIBLIOTECAS SCARLETNX ANTES DO APK ====="
EXTRA="$OUT/snx-stage"
rm -rf "$EXTRA"
mkdir -p "$EXTRA/lib/arm64-v8a" "$EXTRA/assets/licenses"
SNLIB="$EXTRA/lib/arm64-v8a"
# Cross-check against the previous LASRecomp test's native library names.
# That stage is NOT modified; the freshly compiled stage is made afterwards.
MAINLIB="$BASE/stage/lib/arm64-v8a"
unzip -p "$SNX_APK" lib/arm64-v8a/libscarletnx.so > "$SNLIB/libscarletnx.so"
[ -s "$SNLIB/libscarletnx.so" ] || die "Falha ao extrair runtime"
# Do not use grep -q here: with "set -o pipefail" and a big symbol
# table, an early grep match may SIGPIPE llvm-nm and incorrectly fail the build.
# Save the whole table once and check it AFTER llvm-nm has exited normally.
RUNTIME_SYMBOLS="$CACHE/scarletnx-runtime-exports.txt"
if ! llvm-nm -D --defined-only "$SNLIB/libscarletnx.so" > "$RUNTIME_SYMBOLS"; then
  die "Nao foi possivel ler os simbolos do runtime ScarletNX"
fi
# The entire nm table is already saved. Reading it from disk avoids SIGPIPE
# false negatives caused by grep -q while the producer is still writing.
if ! grep -E '[[:space:]]main(@[^[:space:]]*)?$' "$RUNTIME_SYMBOLS" >/dev/null; then
  echo '===== ENTRADAS EXPORTADAS PELO RUNTIME ====='
  grep -Ei '(main|scarlet|snx|SDL_)' "$RUNTIME_SYMBOLS" | tail -45 || true
  echo "ScarletNX APK utilizado: $SNX_APK"
  die 'O runtime ScarletNX nao exporta main. Nao vamos iniciar com ABI errada.'
fi
echo 'SCARLETNX RUNTIME ENTRY VERIFIED:'
grep -E '[[:space:]]main(@[^[:space:]]*)?$' "$RUNTIME_SYMBOLS" | head -1

# Import original native dependencies and namespace any ELF SONAME collision
# with LASRecomp's own JNI/runtime libraries. Different game processes isolate SDL.
MAP="$CACHE/library-name-map.txt"
: > "$MAP"
COPIED="$CACHE/packaged-scarlet-libraries.txt"
printf '%s\n' "$SNLIB/libscarletnx.so" > "$COPIED"
while IFS= read -r member; do
  name="$(basename "$member")"
  case "$name" in
    libscarletnx.so|libmain.so|libscarletnx-run.so) continue;;
  esac
  temp="$CACHE/original-$name"
  unzip -p "$SNX_APK" "$member" > "$temp"
  [ -s "$temp" ] || die "Nao extraiu $name"
  dest="$name"
  # Separate process, but the Android linker namespace is still shared by
  # nativeLibraryDir. Rename original ScarletNX dependencies to prevent
  # collisions with the app's SDL, libc++ and runtime .so files.
  dest="libsnx_$(printf %s "$name" | cut -c4-)"
  printf '%s %s\n' "$name" "$dest" >> "$MAP"
  cp "$temp" "$SNLIB/$dest"
  printf '%s\n' "$SNLIB/$dest" >> "$COPIED"
  if [ "$dest" != "$name" ]; then
    patchelf --set-soname "$dest" "$SNLIB/$dest"
  fi
done < <(unzip -Z1 "$SNX_APK" | grep -E '^lib/arm64-v8a/lib[^/]+\.so$' | sort -u)

while IFS= read -r elf; do
  while read -r original replacement; do
    [ -n "$original" ] || continue
    if llvm-readelf -d "$elf" | grep -Fq "Shared library: [$original]"; then
      patchelf --replace-needed "$original" "$replacement" "$elf"
    fi
  done < "$MAP"
done < "$COPIED"

cp -L "$SNX_CODE" "$SNLIB/libmario_snx.so"
cp android/licenses/RadialGamePad-GPL-3.0.txt "$EXTRA/assets/licenses/ScarletNX-GPL-3.0.txt"
cat > "$EXTRA/assets/licenses/ScarletNX-SOURCE.txt" <<'NOTICE'
ScarletNX experimental runtime (GPL-3.0-or-later):
https://github.com/scarletnx/ScarletNX
Copyright 2026 the ScarletNX contributors.
A test APK built locally from user-provided binaries; do not redistribute
Nintendo game dumps, extracted data, or Nintendo-derived generated code.
Distributing GPL-covered binaries requires corresponding source and compliance.
NOTICE

# Native dependencies must be present in the final APK or Android system.
while IFS= read -r elf; do
  while IFS= read -r dep; do
    [ -n "$dep" ] || continue
    [ ! -s "$SNLIB/$dep" ] || continue
    [ ! -s "$MAINLIB/$dep" ] || continue
    case "$dep" in
      libc.so|libm.so|libdl.so|liblog.so|libandroid.so|libz.so|libvulkan.so|libEGL.so|libGLESv1_CM.so|libGLESv2.so|libGLESv3.so|libOpenSLES.so|libaaudio.so|libmediandk.so|libjnigraphics.so|libstdc++.so) continue;;
    esac
    die "Dependencia ScarletNX ausente: $dep"
  done < <(llvm-readelf -d "$elf" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p')
done < "$COPIED"

# Add all native libraries to the normal Android app's JNI staging BEFORE
# the APK is assembled and signed, not to an already-built ZIP. Android's
# package manager will see these as normal nativeLibraryDir entries.
export LASRECOMP_SNX_STAGE_LIB_DIR="$SNLIB"
export LASRECOMP_SNX_STAGE_LICENSE_DIR="$EXTRA/assets/licenses"

# Android crash identified: ScarletNX's SDL 3.4.18 JNI_OnLoad requires
# SDLActivity.nativeSetupJNI()V. The LASRecomp-pinned SDL 3.2.22 Java declares
# nativeSetupJNI()I and aborts ART during System.loadLibrary(scarletnx).
# Fetch ONLY the pinned upstream SDL Java sources into a separate cache.
# Do not switch or clean the LASRecomp SDL 3.2.22 checkout/native build.
SDL_SOURCES="${LASRECOMP_CACHE:-$HOME/.cache/lasrecomp-termux}/src/sdl3"
SDL_VERSION=release-3.4.18
SDL_JAVA_CACHE="$CACHE/sdl-$SDL_VERSION"
SDL_JAVA="$SDL_JAVA_CACHE/android-project/app/src/main/java"
if [ ! -s "$SDL_JAVA/org/libsdl/app/SDLActivity.java" ]; then
  [ -d "$SDL_SOURCES/.git" ] || die "Checkout do SDL do LASRecomp ausente: $SDL_SOURCES"
  echo "===== OBTENDO APENAS SDL JAVA COMPATIVEL COM SCARLETNX ($SDL_VERSION) ====="
  git -C "$SDL_SOURCES" fetch -q --depth 1 origin \
    "refs/tags/$SDL_VERSION:refs/tags/$SDL_VERSION" ||
    die "Nao foi possivel obter as classes Java SDL $SDL_VERSION"
  mkdir -p "$SDL_JAVA_CACHE"
  git -C "$SDL_SOURCES" archive "$SDL_VERSION" android-project/app/src/main/java |
    tar -xf - -C "$SDL_JAVA_CACHE" ||
    die "Nao foi possivel extrair as classes Java SDL $SDL_VERSION"
fi
grep -F 'native void nativeSetupJNI()' "$SDL_JAVA/org/libsdl/app/SDLActivity.java" >/dev/null ||
  die "A classe SDLActivity nao corresponde ao runtime ScarletNX"
export LASRECOMP_SNX_SDL_JAVA_DIR="$SDL_JAVA"
echo "SCARLETNX JNI: SDLActivity.nativeSetupJNI()V compatível"
echo "===== COMPILANDO E ASSINANDO APK COM SCARLETNX INTEGRADO ====="
bash compilar-lasrecomp-termux.sh
APK="$OUT/Mario-SNX-Runtime-BOOT.apk"
[ -s "$APK" ] || die "APK final nao foi produzido"

# The main build script already verified and signed the completed archive;
# this second verification ensures the file delivered to Downloads is correct.
python3 - "$APK" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    for n in ["lib/arm64-v8a/libscarletnx.so", "lib/arm64-v8a/libmario_snx.so"]:
        f = z.getinfo(n)
        print("BIBLIOTECA INSTALAVEL:", n, f.file_size, "bytes")
        if f.file_size < 100000:
            raise SystemExit("ERRO: arquivo nativo pequeno ou ausente: " + n)
PY
mkdir -p /storage/emulated/0/Download/MarioRecomp
cp -f "$APK" /storage/emulated/0/Download/MarioRecomp/Mario-SNX-Runtime-BOOT.apk
echo "===== APK SNX PRONTO ====="
echo "APK: /storage/emulated/0/Download/MarioRecomp/Mario-SNX-Runtime-BOOT.apk"
echo "Tela: Mario SNX Runtime — diagnóstico 3"
echo "Botao: INICIAR MARIO — CPU ScarletNX"
echo "Se nao abrir, use Salvar log. O log identifica a biblioteca ausente."
