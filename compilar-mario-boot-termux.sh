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
# Repeated unconditional B instructions sharing a join can mark switch-like
# case entries at B+4. Unlike a blind resume anchor, require the observed PC
# to be present in that static cluster before any game-code recompilation.
if [[ -n "${MARIO_CASE_CLUSTER_ANCHOR:-}" ]]; then
    echo "===== MARIO: VERIFICANDO GRUPO DE CASES ARM64 ====="
    python3 tests/test_mario_case_cluster.py
    MARIO_CASE_POINTS="$(python3 -u tools/mario_case_cluster.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --target "$MARIO_CASE_CLUSTER_ANCHOR" \
        --limit "${MARIO_CASE_CLUSTER_LIMIT:-12}" \
        --budget-bytes "${MARIO_CASE_CLUSTER_BYTES:-131072}" \
        --max-block-bytes "${MARIO_CASE_CLUSTER_BLOCK_BYTES:-16384}" \
        --radius "${MARIO_CASE_CLUSTER_RADIUS:-0x4000}")"
    if [[ -n "$MARIO_CASE_POINTS" ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_CASE_POINTS"
        echo "Blocos de cases verificados: $MARIO_CASE_POINTS"
    else
        echo "Grupo de cases ja coberto; reutilizando cache."
    fi
fi
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
        --module "$MARIO_SWITCH_MODULE" --anchor "$MARIO_SWITCH_RVA" --allow-empty \
        --max-blocks "${MARIO_STATIC_SWITCH_BLOCKS:-16}" \
        --budget-bytes "${MARIO_STATIC_SWITCH_BUDGET:-131072}" \
        --max-block-bytes "${MARIO_STATIC_SWITCH_BLOCK_BYTES:-16384}")"
    if [[ -n "$MARIO_SWITCH_ENTRIES" ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_SWITCH_ENTRIES"
        echo "Blocos estaticos selecionados: $MARIO_SWITCH_ENTRIES"
    else
        echo "Tabela verificada, sem novas entradas pendentes; mantendo cache."
    fi
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
# Automatic coverage from verified ADRP/ADD/ADR/LDRB/BR jump tables.
# Unlike crash-address batches, these targets are recovered from the original
# NSO's read-only tables, bounded as whole owning functions before repair.
if [[ "${MARIO_VERIFIED_SWITCHES:-1}" == full ]]; then
    # Explicit exhaustive census: reject incomplete plans BEFORE any generated
    # code or linked library is modified. Both modules must pass. One
    # transactional resume repair below then updates only affected C chunks.
    # Do not enable this as the default: a comprehensive repair is larger
    # than the legacy limited per-APK selection.
    echo "===== MARIO: COBERTURA ESTRUTURAL DE TODAS AS TABELAS COMPROVADAS ====="
    python3 tests/test_mario_static_switches.py
    python3 -c 'import capstone' >/dev/null 2>&1 || {
        echo "ERRO: modo full exige python-capstone; nada sera recompilado." >&2
        exit 1
    }
    for MARIO_SWITCH_NAME in main sdk; do
        echo "===== PLANEJAMENTO ESTRITO (SOMENTE LEITURA): $MARIO_SWITCH_NAME ====="
        MARIO_VERIFIED_POINTS="$(python3 -u tools/mario_static_switches.py \
            --game "$MARIO_GAME" --output "$MARIO_CODE" \
            --module "$MARIO_SWITCH_NAME" --all-verified --require-complete \
            --max-blocks "${MARIO_VERIFIED_SWITCH_BLOCKS:-256}" \
            --budget-bytes "${MARIO_VERIFIED_SWITCH_BYTES:-1048576}" \
            --max-block-bytes "${MARIO_VERIFIED_SWITCH_BLOCK_BYTES:-65536}")"
        if [[ -n "$MARIO_VERIFIED_POINTS" ]]; then
            MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_VERIFIED_POINTS"
            read -r -a MARIO_SWITCH_PLAN <<< "$MARIO_VERIFIED_POINTS"
            echo "Plano completo $MARIO_SWITCH_NAME: ${#MARIO_SWITCH_PLAN[@]} blocos validados."
        else
            echo "Plano completo $MARIO_SWITCH_NAME: nenhum destino pendente."
        fi
    done
elif [[ "${MARIO_VERIFIED_SWITCHES:-1}" == 1 ]]; then
    echo "===== MARIO: TABELAS DE SALTO VERIFICADAS (GLOBAL) ====="
    python3 tests/test_mario_static_switches.py
    if python3 -c 'import capstone' >/dev/null 2>&1; then
        for MARIO_SWITCH_NAME in main sdk; do
            MARIO_VERIFIED_POINTS="$(python3 -u tools/mario_static_switches.py \
                --game "$MARIO_GAME" --output "$MARIO_CODE" \
                --module "$MARIO_SWITCH_NAME" --all-verified \
                --max-blocks "${MARIO_VERIFIED_SWITCH_BLOCKS:-16}" \
                --budget-bytes "${MARIO_VERIFIED_SWITCH_BYTES:-131072}" \
                --max-block-bytes "${MARIO_VERIFIED_SWITCH_BLOCK_BYTES:-16384}")"
            if [[ -n "$MARIO_VERIFIED_POINTS" ]]; then
                MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_VERIFIED_POINTS"
                echo "Tabelas verificadas $MARIO_SWITCH_NAME: $MARIO_VERIFIED_POINTS"
            fi
        done
    else
        echo "AVISO: python-capstone indisponivel; varredura de tabelas ignorada."
        echo "Para habilitar depois: pkg install python-capstone"
    fi
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
# New observed post-Start indirect destination (Mario-Recomp-boot 10).
# Plan the containing block plus a bounded local cohort. The callsite
# is inspected by the existing BL/BLR classifier before recompilation.
if [[ "${MARIO_NEXT_BATCH:-1}" == 1 ]]; then
    echo "===== MARIO: REENTRADAS DA PROXIMA REGIAO ====="
    MARIO_NEXT_POINTS="$(python3 -u tools/mario_resume_batch.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --anchor main:0x76d870 --return-site main:0x76d638 \
        --limit "${MARIO_NEXT_BATCH_LIMIT:-12}" \
        --budget-bytes "${MARIO_NEXT_BATCH_BYTES:-131072}" \
        --radius 4096 --max-block-bytes 16384 \
        --nearby-radius 4096 --prefer-forward 1 --allow-empty)"
    if [[ -n "$MARIO_NEXT_POINTS" ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_NEXT_POINTS"
        echo "Blocos adicionais: $MARIO_NEXT_POINTS"
    else
        echo "Nova regiao ja coberta; reutilizando cache."
    fi
fi
# Observed crash 11: main+0x8c6500 reached with LR main+0x8c2844,
# target was in x11. Repair its owner and a bounded nearby cohort.
if [[ "${MARIO_THIRD_BATCH:-1}" == 1 ]]; then
    echo "===== MARIO: COBERTURA DA REGIAO 0x8C6500 ====="
    MARIO_THIRD_POINTS="$(python3 -u tools/mario_resume_batch.py \
        --game "$MARIO_GAME" --output "$MARIO_CODE" \
        --anchor main:0x8c6500 --return-site main:0x8c2844 \
        --limit "${MARIO_THIRD_BATCH_LIMIT:-12}" \
        --budget-bytes "${MARIO_THIRD_BATCH_BYTES:-131072}" \
        --radius 4096 --max-block-bytes 16384 \
        --nearby-radius 4096 --prefer-forward 1 --allow-empty)"
    if [[ -n "$MARIO_THIRD_POINTS" ]]; then
        MARIO_RESUME_AT="${MARIO_RESUME_AT:+$MARIO_RESUME_AT }$MARIO_THIRD_POINTS"
        echo "Blocos selecionados: $MARIO_THIRD_POINTS"
    else
        echo "Regiao ja coberta; reutilizando cache."
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
#   main+0x76d870 (LR main+0x76d638; Mario-Recomp-boot (10))
#   main+0x8c6500 (LR main+0x8c2844; Mario-Recomp-boot (11))
for MARIO_REQUIRED_ENTRY in main:0x8c6500 main:0x76d870 main:0x791a18 main:0x66c48c main:0x669c74 main:0x3e6384 main:0x66a0fc main:0x8099d0 main:0x8209d0 main:0x834b2c main:0x834d7c main:0x8cfa78 main:0x95009c sdk:0x2bfbd8 sdk:0x376ac0 sdk:0x385134; do
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
