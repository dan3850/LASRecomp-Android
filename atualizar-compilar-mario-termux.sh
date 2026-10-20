#!/data/data/com.termux/files/usr/bin/bash
# Update the existing remote Mario branch without discarding work or caches.
set -euo pipefail

mario_update_checkout() (
    # Run in a subshell so the recovery trap covers only the Git transition.
    local mario_source mario_original mario_target mario_pending='' mario_backup=''
    local mario_backup_root mario_before mario_saved
    [[ ! -d "$(git rev-parse --git-path rebase-merge)" &&
       ! -d "$(git rev-parse --git-path rebase-apply)" &&
       ! -f "$(git rev-parse --git-path MERGE_HEAD)" &&
       ! -f "$(git rev-parse --git-path CHERRY_PICK_HEAD)" &&
       ! -f "$(git rev-parse --git-path REVERT_HEAD)" &&
       -z "$(git ls-files --unmerged)" ]] || {
        echo "ERRO: existe uma operacao Git pendente. Arquivos preservados." >&2; return 1;
    }
    git fetch --no-tags origin "refs/heads/$mario_branch:refs/remotes/origin/$mario_branch"
    mario_target="$(git rev-parse "refs/remotes/origin/$mario_branch")"
    mario_source="$(git branch --show-current)"
    mario_original="$(git rev-parse HEAD)"
    if git show-ref --verify --quiet "refs/heads/$mario_branch"; then
        git merge-base --is-ancestor "refs/heads/$mario_branch" "$mario_target" || {
            echo "ERRO: $mario_branch possui commits locais fora do origin. Nada foi descartado." >&2
            return 1
        }
    fi

    mario_restore_on_error() {
        local mario_result=$?
        trap - EXIT
        if [[ -n "$mario_pending" ]]; then
            if [[ -n "$mario_source" ]]; then
                git switch --no-overwrite-ignore "$mario_source" || true
            else
                git switch --no-overwrite-ignore --detach "$mario_original" || true
            fi
            if [[ "$(git rev-parse HEAD)" == "$mario_original" &&
                  "$(git branch --show-current)" == "$mario_source" ]]; then
                git stash apply --index "$mario_pending" || mario_result=1
            fi
            echo "Backup local mantido: $mario_backup (stash $mario_pending)" >&2
        fi
        exit "$mario_result"
    }

    if [[ "$mario_source" != "$mario_branch" || "$mario_original" != "$mario_target" ]] &&
       [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
        # Keep source-branch edits out of the Mario build. Ignored compilation
        # caches are deliberately excluded from this local-only backup.
        mario_backup_root="$(git rev-parse --git-path mario-update-backups)"
        mkdir -p "$mario_backup_root"
        mario_backup="$(mktemp -d "$mario_backup_root/$(date +%Y%m%d-%H%M%S)-XXXXXX")"
        git diff --binary --cached > "$mario_backup/index.patch"
        git diff --binary > "$mario_backup/working-tree.patch"
        git status --short --untracked-files=all > "$mario_backup/status.txt"
        printf '%s\n%s\n' "$mario_source" "$mario_original" > "$mario_backup/origem.txt"
        mario_before="$(git rev-parse --verify refs/stash 2>/dev/null || true)"
        git -c user.name='Mario local backup' -c user.email='mario-local@localhost' \
            stash push --include-untracked --message "Mario: preservar $mario_source $mario_original"
        mario_saved="$(git rev-parse --verify refs/stash)"
        [[ -n "$mario_saved" && "$mario_saved" != "$mario_before" ]] || {
            echo "ERRO: backup Git nao foi criado. Confira $mario_backup." >&2; return 1;
        }
        mario_pending="$mario_saved"
        trap mario_restore_on_error EXIT
        printf '%s\n' "$mario_saved" > "$mario_backup/stash.txt"
        [[ -z "$(git status --porcelain --untracked-files=all)" ]] || {
            echo "ERRO: ha alteracoes que o Git nao conseguiu guardar. Backup: $mario_backup" >&2
            return 1
        }
    fi
    if [[ "$mario_source" != "$mario_branch" ]]; then
        if git show-ref --verify --quiet "refs/heads/$mario_branch"; then
            git switch --no-overwrite-ignore "$mario_branch"
        else
            # This is the branch already present on origin, with the same name.
            git switch --no-overwrite-ignore --track -c "$mario_branch" "refs/remotes/origin/$mario_branch"
        fi
    fi
    git merge --ff-only --no-overwrite-ignore "$mario_target"
    if [[ -n "$mario_pending" ]]; then
        mario_pending=''
        if [[ "$mario_source" == "$mario_branch" ]]; then
            if ! git stash apply --index "$mario_saved"; then
                echo "ERRO: conflito nas edicoes do Mario; compilacao interrompida. Backup: $mario_backup" >&2
                return 1
            fi
            echo "Edicoes locais do Mario restauradas. Backup: $mario_backup"
        else
            echo "Edicoes de ${mario_source:-HEAD destacado} guardadas em $mario_backup"
            echo "STASH_ORIGEM=$mario_saved (mantido localmente; nao aplicado ao Mario)"
        fi
    fi
    trap - EXIT
)

mario_build_main() {
    local mario_root mario_branch mario_game mario_code mario_apk
    # MARIO_PROJECT also permits running a freshly fetched copy of this script
    # when the currently checked-out branch does not yet contain it.
    mario_root="$(cd "${MARIO_PROJECT:-$(dirname "${BASH_SOURCE[0]}")}" && pwd)"
    mario_branch="android/mario-full-recompiler-test"
    mario_game="${1:-/storage/emulated/0/SwitchRoms/Super-extraido}"
    mario_code="$mario_root/build/private-mario-full-test"
    mario_apk="$mario_root/build/mario-android-boot/Mario-Recomp-Boot-Test.apk"

    cd "$mario_root"
    [[ "$(uname -m)" == aarch64 && "${PREFIX:-}" == /data/data/com.termux/files/usr ]] || {
        echo "ERRO: execute no Termux ARM64, fora do proot." >&2; return 1;
    }
    case "$(git config --get remote.origin.url)" in
        https://github.com/dan3850/LASRecomp-Android|https://github.com/dan3850/LASRecomp-Android.git|git@github.com:dan3850/LASRecomp-Android.git) ;;
        *) echo "ERRO: origin nao corresponde a dan3850/LASRecomp-Android." >&2; return 1 ;;
    esac
    [[ -f "$mario_game/exefs/main" && -f "$mario_game/exefs/sdk" ]] || {
        echo "ERRO: exefs/main ou exefs/sdk ausente em $mario_game." >&2; return 1;
    }
    echo "BRANCH=$(git branch --show-current)"
    echo "HEAD_ANTES=$(git rev-parse HEAD)"
    git status --short
    mario_update_checkout
    [[ "$(git branch --show-current)" == "$mario_branch" ]] || {
        echo "ERRO: branch exigida nao foi selecionada." >&2; return 1;
    }
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
    echo "===== REGRESSAO: CAPTURA DE THREADS ====="
    python3 tests/test_mario_thread_capture.py

    if [[ ! -s "$mario_code/libmario_test.so" || ! -s "$mario_code/build-report.json" ]]; then
        echo "Biblioteca ou relatorio ausente: gerando a partir dos seus arquivos locais."
        bash compilar-mario-full-test-termux.sh "$mario_game"
    else
        echo "Reutilizando biblioteca recompilada e objetos main/sdk existentes."
    fi
    # Repair only when explicitly requested. The boot script validates
    # targets, input hashes, block sizes, and the bounded optional batch.
    # Without MARIO_RESUME_AT or MARIO_BATCH_ANCHOR, no guest code is rebuilt.
    if [[ -n "${MARIO_RESUME_AT:-}" ]]; then
        echo "MARIO_RESUME_AT=$MARIO_RESUME_AT"
    fi
    if [[ -n "${MARIO_BATCH_ANCHOR:-}" ]]; then
        echo "MARIO_BATCH_ANCHOR=$MARIO_BATCH_ANCHOR"
        if [[ -n "${MARIO_BATCH_RETURN_SITE:-}" ]]; then
            echo "MARIO_BATCH_RETURN_SITE=$MARIO_BATCH_RETURN_SITE"
        fi
    elif [[ -n "${MARIO_BATCH_RETURN_SITE:-}" ]]; then
        echo "ERRO: MARIO_BATCH_RETURN_SITE exige MARIO_BATCH_ANCHOR." >&2
        return 1
    fi
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
