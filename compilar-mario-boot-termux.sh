#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
MARIO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$MARIO_ROOT"
[[ "$(uname -m)" == aarch64 && "${PREFIX:-/data/data/com.termux/files/usr}" == /data/data/com.termux/files/usr ]] || {
    echo "ERRO: execute no Termux ARM64, fora de proot." >&2; exit 1;
}
[[ "$(git branch --show-current)" == android/mario-full-recompiler-test ]] || {
    echo "ERRO: esta compilacao exige android/mario-full-recompiler-test." >&2; exit 1;
}
MARIO_GAME="${1:-/storage/emulated/0/SwitchRoms/Super-extraido}"
MARIO_CODE="$MARIO_ROOT/build/private-mario-full-test"
MARIO_BOOT="$MARIO_ROOT/build/mario-android-boot"
echo "BRANCH=$(git branch --show-current)"
echo "HEAD=$(git rev-parse HEAD)"
if [[ -n "${MARIO_RESUME_AT:-}" ]]; then
    read -r -a MARIO_RESUME_POINTS <<< "$MARIO_RESUME_AT"
    MARIO_RESUME_ARGS=()
    for MARIO_POINT in "${MARIO_RESUME_POINTS[@]}"; do
        MARIO_RESUME_ARGS+=(--resume-at "$MARIO_POINT")
    done
    python3 -u tools/mario_resume_repair.py --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --jobs "${MARIO_JOBS:-2}" "${MARIO_RESUME_ARGS[@]}" \
        2>&1 | tee -a "$MARIO_CODE/reentrada.log"
fi
python3 tools/mario_boot_profile.py --report "$MARIO_CODE/build-report.json" \
    --game "$MARIO_GAME" --output "$MARIO_BOOT/profile"
echo "Reutilizando biblioteca existente: $MARIO_CODE/libmario_test.so"
echo "Objetos main/sdk fora dos blocos de reentrada solicitados permanecem em cache."
export LASRECOMP_BUILD_OUT="$MARIO_BOOT"
export LASRECOMP_MARIO_PROFILE="$MARIO_BOOT/profile/mario_profile_config.h"
export LASRECOMP_MANIFEST="$MARIO_ROOT/android/mario/AndroidManifest.xml"
export LASRECOMP_APK_FILENAME="Mario-Recomp-Boot-Test.apk"
export LASRECOMP_DOWNLOAD_FOLDER="MarioRecomp"
export LASRECOMP_GAME_SO="$MARIO_CODE/libmario_test.so"
bash compilar-lasrecomp-termux.sh
echo "BRANCH=$(git branch --show-current)"
echo "HEAD=$(git rev-parse HEAD)"
echo "APK=$MARIO_BOOT/Mario-Recomp-Boot-Test.apk"
echo "LOG=$MARIO_BOOT/compilacao.log"
echo "APK para teste de inicializacao; o boot real precisa ser verificado no aparelho."
