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
[[ -d "$PROJECT/.git" ]] || fail "Nao e um checkout Git: $PROJECT"
cd "$PROJECT"
case "$(git remote get-url origin)" in
    https://github.com/dan3850/LASRecomp-Android|https://github.com/dan3850/LASRecomp-Android.git|git@github.com:dan3850/LASRecomp-Android.git) ;;
    *) fail 'O origin deste projeto nao e dan3850/LASRecomp-Android.' ;;
esac
# Arquivos nao rastreados (como backups e bibliotecas privadas) ficam intactos.
git diff --quiet && git diff --cached --quiet ||
    fail 'Existem alteracoes rastreadas locais. Nada foi apagado nem sobrescrito.'
[[ ! -d .git/rebase-merge && ! -d .git/rebase-apply && ! -f .git/MERGE_HEAD ]] ||
    fail 'Existe uma operacao Git pendente. Nada foi alterado.'
git fetch origin "refs/heads/$BRANCH"
if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
        git switch "$BRANCH"
    else
        git switch -c "$BRANCH" FETCH_HEAD
    fi
fi
git merge --ff-only FETCH_HEAD
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail 'Branch incorreta.'
COMMIT="$(git rev-parse --short=12 HEAD)"
printf '\nPROJETO: %s\nBRANCH: %s\nHEAD: %s\n' "$PROJECT" "$BRANCH" "$COMMIT"
# O script existente reutiliza os objetos e dependencias, empacota o app,
# reutiliza a chave local persistente e verifica a assinatura com apksigner.
bash "$PROJECT/compilar-lasrecomp-termux.sh"
APK="$PROJECT/build/termux-native/LASRecomp-Android-Termux.apk"
[[ -s "$APK" ]] || fail "APK nao foi gerado: $APK"
DEST="${LASRECOMP_OUTPUT:-/storage/emulated/0/Download/LASRecomp}"
mkdir -p "$DEST"
cp -f "$APK" "$DEST/LASRecomp-pasta-externa-$COMMIT-signed.apk"
git archive --format=zip --output="$DEST/LASRecomp-fontes-$COMMIT.zip" HEAD
printf '\nAPK ASSINADO: %s\nFONTES COMPLETOS: %s\nLOG: %s\n' \
    "$DEST/LASRecomp-pasta-externa-$COMMIT-signed.apk" \
    "$DEST/LASRecomp-fontes-$COMMIT.zip" "$PROJECT/build/termux-native/compilacao.log"
}
main "$@"
