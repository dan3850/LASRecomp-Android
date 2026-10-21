#!/data/data/com.termux/files/usr/bin/bash
# Experimental on-device ScarletNX module probe; no guest execution.
# Reuses LASRecomp's compiled Mario game and Android/Termux build caches.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
die() { echo "ERRO: $*" >&2; exit 1; }

[[ "$(uname -m)" == aarch64 ]] || die "Execute no Termux ARM64."
[[ "$(git branch --show-current)" == android/mario-snx-library-probe ]] ||
  die "Selecione a branch android/mario-snx-library-probe."

SNX_SO="${MARIO_SNX_CODE_SO:-/storage/emulated/0/Download/010028600EBDA000/010028600EBDA000_code.so}"
SNX_ABI_FILE="${MARIO_SNX_ABI_FILE:-/storage/emulated/0/Download/010028600EBDA000/010028600EBDA000.abi}"
GAME="${MARIO_GAME:-/storage/emulated/0/SwitchRoms/Super-extraido}"
CODE="$ROOT/build/private-mario-full-test"
OUT="$ROOT/build/mario-android-boot"
PROFILE="$OUT/profile/mario_profile_config.h"
APK="$OUT/Mario-SNX-Lib-Test.apk"
SIGNED="$OUT/Mario-SNX-Lib-Test.signed.apk"
[[ -s "$SNX_SO" ]] || die "Biblioteca do ScarletNX nao encontrada: $SNX_SO"
[[ -s "$CODE/libmario_test.so" ]] ||
  die "Biblioteca LASRecomp existente nao encontrada em $CODE. Este script nao recompila o codigo do jogo."
[[ -s "$CODE/build-report.json" ]] || die "Relatorio Mario ausente: $CODE/build-report.json"
command -v llvm-readelf >/dev/null || die "llvm-readelf ausente"
command -v llvm-nm >/dev/null || die "llvm-nm ausente"
command -v zip >/dev/null || die "zip ausente"
command -v unzip >/dev/null || die "unzip ausente"

llvm-readelf -h "$SNX_SO" | grep -Eq 'Machine:.*AArch64' || die "SNX: nao e AArch64"
llvm-nm -D --defined-only "$SNX_SO" | grep -Eq '[[:space:]]snx_module$' ||
  die "SNX: snx_module nao exportado"
if [[ -s "$SNX_ABI_FILE" ]]; then
  [[ "$(cat "$SNX_ABI_FILE")" == 12 ]] || die "Biblioteca SNX nao informa ABI 12"
fi
echo "===== TESTE DA ESTRUTURA ABI ====="
python3 tests/test_mario_snx_probe.py

# Read-only: recovers the existing game's boot profile, not any ARM64 blocks.
if [[ ! -s "$PROFILE" || ! -s "$OUT/profile/mario_boot_profile.json" ]]; then
  python3 tools/mario_boot_profile.py --report "$CODE/build-report.json" \
    --game "$GAME" --output "$OUT/profile"
fi

export LASRECOMP_BUILD_OUT="$OUT"
export LASRECOMP_MARIO_PROFILE="$PROFILE"
export LASRECOMP_MANIFEST="$ROOT/android/mario/AndroidManifest.xml"
export LASRECOMP_APK_FILENAME="Mario-SNX-Lib-Test.apk"
export LASRECOMP_DOWNLOAD_FOLDER="MarioRecomp"
export LASRECOMP_GAME_SO="$CODE/libmario_test.so"
echo "===== COMPILANDO APK EXPERIMENTAL (caches preservados) ====="
bash "$ROOT/compilar-lasrecomp-termux.sh"

# The native ELF is user-generated and MUST remain local: never commit/upload
# it to GitHub. Inject into the already produced UNSIGNED APK and sign it.
[[ -s "$OUT/unsigned.apk" ]] || die "APK temporario nao foi produzido"
[[ -s "$HOME/.lasrecomp-android-debug.keystore" || -s "${LASRECOMP_KEYSTORE:-}" ]] ||
  die "Chave de assinatura nao encontrada"
STAGING="$OUT/snx-extra"
mkdir -p "$STAGING/lib/arm64-v8a"
cp -L "$SNX_SO" "$STAGING/lib/arm64-v8a/libmario_snx.so"
cp "$OUT/unsigned.apk" "$OUT/snx-unsigned.apk"
echo "===== ADICIONANDO BIBLIOTECA SNX AO APK ====="
(cd "$STAGING" && zip -q -0 "$OUT/snx-unsigned.apk" lib/arm64-v8a/libmario_snx.so)
unzip -Z1 "$OUT/snx-unsigned.apk" | grep -Fx 'lib/arm64-v8a/libmario_snx.so' >/dev/null ||
  die "O APK nao contem libmario_snx.so"

ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-${PREFIX:-/data/data/com.termux/files/usr}/opt/android-sdk}}"
[[ -d "$ANDROID_HOME/build-tools" ]] || ANDROID_HOME="$HOME/android-sdk"
APKSIGNER="$(command -v apksigner || true)"
APKSIGNER_JAR=""
if [[ -z "$APKSIGNER" ]]; then
  APKSIGNER_JAR="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner.jar 2>/dev/null | sort -V | tail -1)"
  [[ -s "$APKSIGNER_JAR" ]] || die "apksigner ausente"
fi
signer() {
  if [[ -n "$APKSIGNER" ]]; then "$APKSIGNER" "$@"
  else java -jar "$APKSIGNER_JAR" "$@"; fi
}
KEYSTORE="${LASRECOMP_KEYSTORE:-$HOME/.lasrecomp-android-debug.keystore}"
signer sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
  --ks-pass pass:android --key-pass pass:android \
  --out "$SIGNED" "$OUT/snx-unsigned.apk"
signer verify "$SIGNED"
mv -f "$SIGNED" "$APK"

mkdir -p "/storage/emulated/0/Download/MarioRecomp"
cp "$APK" "/storage/emulated/0/Download/MarioRecomp/Mario-SNX-Lib-Test.apk"
echo "===== PRONTO ====="
echo "APK: /storage/emulated/0/Download/MarioRecomp/Mario-SNX-Lib-Test.apk"
echo "INSTALAR E ABRIR: Mario ScarletNX TESTE"
echo "BOTAO: Testar biblioteca ScarletNX (sem iniciar o jogo)"
echo "Resultado: exibido na tela e salvo em mario-snx-probe.txt, via Salvar log"
echo "Este teste NAO executa o jogo; para isso falta integrar o runtime ScarletNX."
