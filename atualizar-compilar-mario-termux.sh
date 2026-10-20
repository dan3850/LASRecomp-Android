#!/data/data/com.termux/files/usr/bin/bash
# Update and build only the existing Mario branch; never reset, stash or clean.
set -euo pipefail

mario_build_main() {
    local mario_root mario_branch mario_game mario_code mario_apk
    mario_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    mario_branch="android/mario-full-recompiler-test"
    mario_game="${1:-/storage/emulated/0/SwitchRoms/Super-extraido}"
    mario_code="$mario_root/build/private-mario-full-test"
    mario_apk="$mario_root/build/mario-android-boot/Mario-Recomp-Boot-Test.apk"

    cd "$mario_root"
    [[ "$(uname -m)" == aarch64 && "${PREFIX:-}" == /data/data/com.termux/files/usr ]] || {
        echo "ERRO: execute no Termux ARM64, fora do proot." >&2; return 1;
    }
    [[ "$(git branch --show-current)" == "$mario_branch" ]] || {
        echo "ERRO: branch atual: $(git branch --show-current). Exigida: $mario_branch." >&2
        echo "Nenhuma branch ou alteracao local foi trocada." >&2; return 1;
    }
    [[ -f "$mario_game/exefs/main" && -f "$mario_game/exefs/sdk" ]] || {
        echo "ERRO: exefs/main ou exefs/sdk ausente em $mario_game." >&2; return 1;
    }
    echo "BRANCH=$(git branch --show-current)"
    echo "HEAD_ANTES=$(git rev-parse HEAD)"
    git status --short
    git fetch --no-tags origin "refs/heads/$mario_branch:refs/remotes/origin/$mario_branch"
    if ! git merge --ff-only "refs/remotes/origin/$mario_branch"; then
        echo "ERRO: atualizacao sem sobrescrita impossivel; historico e arquivos locais preservados." >&2
        return 1
    fi
    if ! git diff --quiet HEAD -- runtime/kernel.c tests/kernel_condvar_test.c tests/test_kernel_condvar.py; then
        echo "ERRO: kernel ou teste de regressao possui edicoes locais; nada foi descartado." >&2
        git status --short
        return 1
    fi
    echo "HEAD=$(git rev-parse HEAD)"
    export MARIO_JOBS="${MARIO_JOBS:-2}"
    export LASRECOMP_JOBS="${LASRECOMP_JOBS:-3}"
    echo "===== REGRESSAO: TIMEOUT E POSSE DO MUTEX ====="
    python3 tests/test_kernel_condvar.py
    echo "===== REGRESSAO: BOOTSTRAP, LOADER E DISPATCH ====="
    python3 -m unittest discover -s tests -p test_mario_boot_profile.py -v

    if [[ ! -s "$mario_code/libmario_test.so" || ! -s "$mario_code/build-report.json" ]]; then
        echo "Biblioteca ou relatorio ausente: gerando a partir dos seus arquivos locais."
        bash compilar-mario-full-test-termux.sh "$mario_game"
    else
        echo "Reutilizando biblioteca recompilada e objetos main/sdk existentes."
    fi
    # A kernel-only correction needs no speculative reentry batch. The ordinary
    # boot script validates the existing library and NSO hashes before building.
    env -u MARIO_BATCH_ANCHOR -u MARIO_BATCH_RETURN_SITE -u MARIO_RESUME_AT \
        bash compilar-mario-boot-termux.sh "$mario_game"
    [[ -s "$mario_apk" ]] || { echo "ERRO: APK nao produzido: $mario_apk" >&2; return 1; }
    echo "BRANCH=$(git branch --show-current)"
    echo "HEAD=$(git rev-parse HEAD)"
    echo "APK=$mario_apk"
    if [[ -s /storage/emulated/0/Download/MarioRecomp/Mario-Recomp-Boot-Test.apk ]] &&
       cmp -s "$mario_apk" /storage/emulated/0/Download/MarioRecomp/Mario-Recomp-Boot-Test.apk; then
        echo "APK_DOWNLOAD=/storage/emulated/0/Download/MarioRecomp/Mario-Recomp-Boot-Test.apk"
    fi
    echo "APK compilado e assinatura verificada pelo script nativo. Avanco visual requer teste no aparelho."
}

mario_build_main "$@"
