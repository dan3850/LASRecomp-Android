#!/data/data/com.termux/files/usr/bin/bash
# Atualiza somente a branch experimental, compila incrementalmente e assina.
# Nao apaga arquivos locais, objetos, SDK, NDK ou dependencias em cache.
set -euo pipefail
main() {
BRANCH='android/external-game-folder'
REPOSITORY='https://github.com/dan3850/LASRecomp-Android.git'
fail() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null 2>&1 || fail 'git nao encontrado no Termux.'
[[ "$(uname -m)" == aarch64 && -n "${PREFIX:-}" && "$PREFIX" == /data/data/com.termux/files/usr ]] ||
    fail 'Execute no Termux ARM64, fora de proot.'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${LASRECOMP_PROJECT:-}"
if [[ -z "$PROJECT" && -d "$SCRIPT_DIR/.git" ]]; then PROJECT="$SCRIPT_DIR"; fi
if [[ -z "$PROJECT" ]]; then
    for candidate in "$HOME/LASRecomp-Android" "$HOME/lasrecomp-android"; do
        if [[ -d "$candidate/.git" ]]; then PROJECT="$candidate"; break; fi
    done
fi
PROJECT="${PROJECT:-$HOME/LASRecomp-Android}"
if [[ ! -e "$PROJECT" ]]; then
    git clone --single-branch --branch "$BRANCH" "$REPOSITORY" "$PROJECT"
fi
[[ -e "$PROJECT/.git" ]] || fail "Nao e um checkout Git: $PROJECT"
cd "$PROJECT"
case "$(git config --get remote.origin.url)" in
    https://github.com/dan3850/LASRecomp-Android|https://github.com/dan3850/LASRecomp-Android.git|git@github.com:dan3850/LASRecomp-Android.git) ;;
    *) fail 'O origin deste projeto nao e dan3850/LASRecomp-Android.' ;;
esac
[[ ! -d "$(git rev-parse --git-path rebase-merge)" &&
   ! -d "$(git rev-parse --git-path rebase-apply)" &&
   ! -f "$(git rev-parse --git-path MERGE_HEAD)" &&
   -z "$(git ls-files --unmerged)" ]] ||
    fail 'Existe uma operacao Git pendente. Nada foi alterado.'
git fetch origin "refs/heads/$BRANCH"
FETCHED="$(git rev-parse FETCH_HEAD)"
ORIGINAL_BRANCH="$(git branch --show-current)"
ORIGINAL_HEAD="$(git rev-parse HEAD)"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git merge-base --is-ancestor "refs/heads/$BRANCH" "$FETCHED" ||
        fail "A branch $BRANCH possui commits divergentes. Nada local foi removido."
fi

PENDING_STASH=''
BACKUP=''
restore_changes() {
    local saved="$PENDING_STASH"
    [[ -n "$saved" ]] || return 0
    # Keep the stash as a second backup, even after successful application.
    # Clear the pending flag first: a conflict must not be applied twice.
    PENDING_STASH=''
    if git stash apply --index "$saved"; then
        printf '\nAlteracoes locais restauradas. Backup: %s\n' "$BACKUP"
    else
        printf '\nConflito ao reaplicar alteracoes locais. Backup completo: %s\n' "$BACKUP" >&2
        git status --short >&2
        return 1
    fi
}
update_exit() {
    local result=$?
    trap - EXIT
    if [[ -n "$PENDING_STASH" ]]; then
        # A failed switch/fast-forward should restore the original checkout.
        if [[ -n "$ORIGINAL_BRANCH" ]]; then
            git switch "$ORIGINAL_BRANCH" || true
        else
            git switch --detach "$ORIGINAL_HEAD" || true
        fi
        restore_changes || result=1
    fi
    exit "$result"
}

# Only stash when an update/switch actually needs it. Ignored caches and all
# untracked files stay in place: deliberately no -u/-a, clean or hard reset.
if [[ "$ORIGINAL_BRANCH" != "$BRANCH" || "$ORIGINAL_HEAD" != "$FETCHED" ]]; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
        BACKUP_ROOT="${LASRECOMP_BACKUP_DIR:-$HOME/.local/state/lasrecomp/backups}"
        mkdir -p "$BACKUP_ROOT"
        BACKUP="$(mktemp -d "$BACKUP_ROOT/atualizacao-$(date +%Y%m%d-%H%M%S)-XXXXXX")"
        git diff --binary --cached > "$BACKUP/index.patch"
        git diff --binary > "$BACKUP/working-tree.patch"
        git status --short > "$BACKUP/status.txt"
        printf '%s\n%s\n' "$ORIGINAL_BRANCH" "$ORIGINAL_HEAD" > "$BACKUP/origem.txt"
        printf '\nPreservando alteracoes locais em: %s\n' "$BACKUP"
        git status --short
        BEFORE_STASH="$(git rev-parse --verify refs/stash 2>/dev/null || true)"
        git -c user.name='LASRecomp local backup' -c user.email='lasrecomp-local@localhost' \
            stash push --message "LASRecomp antes de atualizar: $ORIGINAL_BRANCH $ORIGINAL_HEAD"
        SAVED_STASH="$(git rev-parse --verify refs/stash 2>/dev/null || true)"
        [[ -n "$SAVED_STASH" && "$SAVED_STASH" != "$BEFORE_STASH" ]] ||
            fail "O Git nao criou um novo backup. As alteracoes continuam no projeto: $BACKUP"
        PENDING_STASH="$SAVED_STASH"
        printf '%s\n' "$PENDING_STASH" > "$BACKUP/stash.txt"
        trap update_exit EXIT
        git diff --quiet && git diff --cached --quiet ||
            fail "Nao foi possivel preservar todas as alteracoes. Backup: $BACKUP"
    fi
fi
if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
        git switch "$BRANCH"
    else
        git switch -c "$BRANCH" "$FETCHED"
    fi
fi
git merge --ff-only "$FETCHED"
restore_changes || fail "Resolva os conflitos indicados antes de compilar. Seus arquivos estao no backup: $BACKUP"
trap - EXIT
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail 'Branch incorreta.'
COMMIT="$(git rev-parse --short=12 HEAD)"
BUILD_ID="$COMMIT"
if ! git diff --quiet || ! git diff --cached --quiet; then BUILD_ID="$COMMIT-local"; fi
printf '\nPROJETO: %s\nBRANCH: %s\nHEAD: %s\n' "$PROJECT" "$BRANCH" "$COMMIT"
# O script existente reutiliza os objetos e dependencias, empacota o app,
# reutiliza a chave local persistente e verifica a assinatura com apksigner.
bash "$PROJECT/compilar-lasrecomp-termux.sh"
APK="$PROJECT/build/termux-native/LASRecomp-Android-Termux.apk"
[[ -s "$APK" ]] || fail "APK nao foi gerado: $APK"
DEST="${LASRECOMP_OUTPUT:-/storage/emulated/0/Download/LASRecomp}"
mkdir -p "$DEST"
cp -f "$APK" "$DEST/LASRecomp-pasta-externa-$BUILD_ID-signed.apk"
# Snapshot tracked source files as actually built, including restored local
# overrides. Read them directly; never walk/copy ignored game data or caches.
python3 - "$DEST/LASRecomp-fontes-$BUILD_ID.zip" <<'PY'
import os, stat, subprocess, sys, zipfile
paths = subprocess.check_output(['git', 'ls-files', '-z']).split(b'\0')
with zipfile.ZipFile(sys.argv[1], 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for raw in dict.fromkeys(paths):
        if not raw:
            continue
        path = os.fsdecode(raw)
        if os.path.islink(path):
            info = zipfile.ZipInfo(path)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, os.fsencode(os.readlink(path)))
        elif os.path.isfile(path):
            archive.write(path, path)
    archive.writestr('LASRECOMP-BUILD-INFO.txt',
        subprocess.check_output(['git', 'log', '-1', '--format=%H%n%s']) +
        subprocess.check_output(['git', 'status', '--short']))
PY
printf '\nAPK ASSINADO: %s\nFONTES COMPLETOS: %s\nLOG: %s\n' \
    "$DEST/LASRecomp-pasta-externa-$BUILD_ID-signed.apk" \
    "$DEST/LASRecomp-fontes-$BUILD_ID.zip" "$PROJECT/build/termux-native/compilacao.log"
}
main "$@"
