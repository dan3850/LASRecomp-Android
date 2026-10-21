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
if [[ -n "${MARIO_STATIC_SWITCH_ANCHOR:-}" ]]; then
    # Verified guarded byte-switch scan: one repair per containing block,
    # not repeated one-address-per-APK attempts. No full code regeneration.
    if [[ ! "$MARIO_STATIC_SWITCH_ANCHOR" =~ ^(main|sdk):0x([0-9a-fA-F]+)$ ]]; then
        echo "ERRO: MARIO_STATIC_SWITCH_ANCHOR exige main:0xOFFSET ou sdk:0xOFFSET." >&2
        exit 1
    fi
    MARIO_SWITCH_MODULE="${BASH_REMATCH[1]}"
    MARIO_SWITCH_RVA="0x${BASH_REMATCH[2]}"
    echo "===== MARIO: TESTANDO TABELAS DE SALTO ARM64 ====="
    python3 tests/test_mario_static_switches.py
    echo "===== MARIO: REENTRADAS ESTATICAS COMPROVADAS ====="
    MARIO_SWITCH_ENTRIES="$(python3 -u tools/mario_static_switches.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --module "$MARIO_SWITCH_MODULE" --anchor "$MARIO_SWITCH_RVA" \
        --max-blocks "${MARIO_STATIC_SWITCH_BLOCKS:-16}" \
        --budget-bytes "${MARIO_STATIC_SWITCH_BUDGET:-131072}" \
        --max-block-bytes "${MARIO_STATIC_SWITCH_BLOCK_BYTES:-16384}")"
    if [[ -z "$MARIO_SWITCH_ENTRIES" ]]; then
        echo "ERRO: sem enderecos comprovados para reparar; nao recompilar." >&2
        exit 1
    fi
    MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_SWITCH_ENTRIES"
    echo "Blocos estaticos selecionados: $MARIO_SWITCH_ENTRIES"
fi
if [[ -n "${MARIO_BATCH_ANCHOR:-}" ]]; then
    # Opt-in, bounded static lookahead. Keep the ordinary incremental build
    # completely unchanged when MARIO_BATCH_ANCHOR is not supplied.
    read -r -a MARIO_BATCH_ANCHORS <<< "$MARIO_BATCH_ANCHOR"
    MARIO_BATCH_ARGS=()
    for MARIO_ANCHOR in "${MARIO_BATCH_ANCHORS[@]}"; do
        MARIO_BATCH_ARGS+=(--anchor "$MARIO_ANCHOR")
    done
    if [[ -n "${MARIO_BATCH_RETURN_SITE:-}" ]]; then
        read -r -a MARIO_RETURN_SITES <<< "$MARIO_BATCH_RETURN_SITE"
        for MARIO_RETURN_SITE in "${MARIO_RETURN_SITES[@]}"; do
            MARIO_BATCH_ARGS+=(--return-site "$MARIO_RETURN_SITE")
        done
    fi
    echo "===== TESTES DA SELECAO DE REENTRADAS ====="
    python3 tests/test_mario_resume_batch.py
    echo "===== MARIO: PLANEJANDO REENTRADAS EM LOTE ====="
    MARIO_BATCH_POINTS="$(python3 -u tools/mario_resume_batch.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --limit "${MARIO_BATCH_LIMIT:-8}" \
        --budget-bytes "${MARIO_BATCH_MAX_BYTES:-65536}" \
        --radius "${MARIO_BATCH_RADIUS:-65536}" \
        --max-block-bytes "${MARIO_BATCH_BLOCK_BYTES:-16384}" \
        --nearby-radius "${MARIO_BATCH_NEARBY_RADIUS:-0}" \
        --prefer-forward "${MARIO_BATCH_PREFER_FORWARD:-0}" \
        "${MARIO_BATCH_ARGS[@]}")"
    [[ -n "$MARIO_BATCH_POINTS" ]] || {
        echo "ERRO: planejamento nao selecionou nenhum bloco." >&2; exit 1;
    }
    MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_BATCH_POINTS"
    echo "Reentradas selecionadas: $MARIO_BATCH_POINTS"
fi
# The post-Start transition has repeatedly branched into neighbouring main
# functions through the same callsite region. Handle BOTH observed destinations
# and their nearby owners before the generic cross-module batch can exhaust its
# per-module quota. Keep a strict block/byte budget and reuse completed repairs.
if [[ "${MARIO_SCENE_BATCH:-1}" == 1 ]]; then
    echo "===== MARIO: COBERTURA LOCAL DA TRANSICAO POS-START ====="
    python3 tests/test_mario_resume_batch.py
    MARIO_SCENE_POINTS="$(python3 -u tools/mario_resume_batch.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --anchor main:0x834b2c --anchor main:0x834d7c \
        --return-site main:0x8d2934 --return-site main:0x8d291c \
        --limit "${MARIO_SCENE_BATCH_LIMIT:-16}" \
        --budget-bytes "${MARIO_SCENE_BATCH_BYTES:-262144}" \
        --radius 8192 --max-block-bytes 16384 \
        --nearby-radius 8192 --prefer-forward 1 --allow-empty)"
    if [[ -n "$MARIO_SCENE_POINTS" ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_SCENE_POINTS"
        echo "Blocos da transicao: $MARIO_SCENE_POINTS"
    else
        echo "Regiao observada ja coberta; reutilizando cache."
    fi
fi
# Automatically analyze nearby primary functions around confirmed late
# dispatch failures, selecting up to 32 independent owners in one pass.
# The planner only reads locally extracted NSOs and the existing dispatch map;
# already repaired owners are skipped. Nothing changes in Vulkan/audio/input.
if [[ "${MARIO_AUTO_BATCH:-1}" == 1 ]]; then
    echo "===== MARIO: REPARO PROATIVO EM LOTE (ATE 32 BLOCOS) ====="
    python3 tests/test_mario_resume_batch.py
    MARIO_AUTO_POINTS="$(python3 -u tools/mario_resume_batch.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --anchor main:0x8099d0 --anchor main:0x8209d0 --anchor main:0x834b2c --anchor main:0x8cfa78 --anchor main:0x95009c \
        --anchor sdk:0x2bfbd8 --anchor sdk:0x376ac0 \
        --limit "${MARIO_AUTO_BATCH_LIMIT:-32}" \
        --budget-bytes "${MARIO_AUTO_BATCH_BYTES:-524288}" \
        --radius "${MARIO_AUTO_BATCH_RADIUS:-65536}" \
        --max-block-bytes "${MARIO_AUTO_BATCH_BLOCK_BYTES:-16384}" \
        --nearby-radius "${MARIO_AUTO_BATCH_NEARBY:-4096}" \
        --prefer-forward 1 --allow-empty)"
    if [[ -n "$MARIO_AUTO_POINTS" ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_AUTO_POINTS"
        echo "Novos blocos selecionados: $MARIO_AUTO_POINTS"
    else
        echo "Todos os blocos candidatos ja foram reparados; reutilizando cache."
    fi
fi
# Verified runtime dispatch gaps. Keep previously confirmed boot repair and
# repair both new missing main-module functions without rebuilding everything.
# Recent missing indirect targets are validated as main or sdk offsets:
#   main+0x66c48c (LR main+0x66d150)
#   main+0x669c74 (LR main+0x6698e0)
#   main+0x834b2c (LR main+0x8d2934; Mario-Recomp-boot (7))
#   main+0x834d7c (LR main+0x8d291c; Mario-Recomp-boot (9))
for MARIO_REQUIRED_ENTRY in main:0x791a18 main:0x66c48c main:0x669c74 main:0x3e6384 main:0x66a0fc main:0x8099d0 main:0x8209d0 main:0x834b2c main:0x834d7c main:0x8cfa78 main:0x95009c sdk:0x2bfbd8 sdk:0x376ac0 sdk:0x385134; do
    if [[ " ${MARIO_RESUME_AT:-} " != *" $MARIO_REQUIRED_ENTRY "* ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_REQUIRED_ENTRY"
    fi
done
echo "===== MARIO: REENTRADAS CONFIRMADAS ====="
echo "$MARIO_RESUME_AT"
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
