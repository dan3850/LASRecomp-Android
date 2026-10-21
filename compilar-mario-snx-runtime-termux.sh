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
echo "===== COMPILANDO APP ANDROID COM CACHES PRESERVADOS ====="
bash compilar-lasrecomp-termux.sh
[ -s "$OUT/unsigned.apk" ] || die "APK base nao produzido"

EXTRA="$OUT/snx-stage"
rm -rf "$EXTRA"
mkdir -p "$EXTRA/lib/arm64-v8a" "$EXTRA/assets/licenses"
SNLIB="$EXTRA/lib/arm64-v8a"
MAINLIB="$OUT/stage/lib/arm64-v8a"
unzip -p "$SNX_APK" lib/arm64-v8a/libscarletnx.so > "$SNLIB/libscarletnx.so"
[ -s "$SNLIB/libscarletnx.so" ] || die "Falha ao extrair runtime"
llvm-nm -D --defined-only "$SNLIB/libscarletnx.so" | grep -Eq '[[:space:]]main$' ||
  die "ScarletNX nao exporta main; runtime incompativel com SDL GameActivity"

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
  if [ -s "$MAINLIB/$name" ]; then
    if cmp -s "$temp" "$MAINLIB/$name"; then continue; fi
    dest="libsnx_$(printf %s "$name" | cut -c4-)"
    printf '%s %s\n' "$name" "$dest" >> "$MAP"
  fi
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

UNSIGNED="$OUT/snx-runtime-unsigned.apk"
cp "$OUT/unsigned.apk" "$UNSIGNED"
(cd "$EXTRA" && zip -q -0 -r "$UNSIGNED" lib && zip -q -r "$UNSIGNED" assets)
unzip -Z1 "$UNSIGNED" | grep -Fx 'lib/arm64-v8a/libscarletnx.so' >/dev/null ||
  die "ScarletNX nao entrou no APK"

ANDROID_HOME="$(printenv ANDROID_HOME || true)"
[ -n "$ANDROID_HOME" ] || ANDROID_HOME="$HOME/android-sdk"
[ -d "$ANDROID_HOME/build-tools" ] || ANDROID_HOME="$HOME/android-sdk"
APKSIGNER="$(command -v apksigner || true)"
APKSIGNER_JAR=""
if [ -z "$APKSIGNER" ]; then
  APKSIGNER_JAR="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner.jar 2>/dev/null | sort -V | tail -1)"
  [ -s "$APKSIGNER_JAR" ] || die "Apksigner ausente"
fi
signer() {
  if [ -n "$APKSIGNER" ]; then "$APKSIGNER" "$@"
  else java -jar "$APKSIGNER_JAR" "$@"; fi
}
KEYSTORE="$(printenv LASRECOMP_KEYSTORE || true)"
[ -n "$KEYSTORE" ] || KEYSTORE="$HOME/.lasrecomp-android-debug.keystore"
[ -s "$KEYSTORE" ] || die "Keystore ausente"
APK="$OUT/Mario-SNX-Runtime-BOOT.apk"
signer sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
  --ks-pass pass:android --key-pass pass:android --out "$APK" "$UNSIGNED"
signer verify "$APK"
mkdir -p /storage/emulated/0/Download/MarioRecomp
cp "$APK" /storage/emulated/0/Download/MarioRecomp/Mario-SNX-Runtime-BOOT.apk
echo "===== CONCLUIDO ====="
echo "APK: /storage/emulated/0/Download/MarioRecomp/Mario-SNX-Runtime-BOOT.apk"
echo "Abrir Mario SNX Runtime TESTE > Selecionar pasta Super-extraido"
echo "Executar Mario pelo runtime ScarletNX (experimental)"
echo "Este primeiro teste copia ExeFS, mas ainda NAO a RomFS de varios GB."
echo "Voltar ao app: Ver ultimo log / Salvar log."
