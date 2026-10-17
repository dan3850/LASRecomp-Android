#!/data/data/com.termux/files/usr/bin/bash
# LASRecomp Android - Eden GMEM incremental, build e assinatura no Termux.
# Sem git reset/clean, sem Actions, sem apagar caches, objetos ou lib privada.
set -euo pipefail

BRANCH='android/eden-startup-pipeline-replay'
RESTORE='e165962fda30e6da119307c1ef44a91fda19afd7'
OPTIMIZATION='1264249c61b80e470b6ee136a269764ff8618530'
REPO='https://github.com/dan3850/LASRecomp-Android.git'
PROJECT="${LASRECOMP_PROJECT:-$HOME/LASRecomp-Android}"
DEST="${LASRECOMP_OUTPUT:-/storage/emulated/0/Download/LASRecomp}"
fail() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -m)" == aarch64 ]] || fail 'Este script deve rodar no Termux ARM64.'
[[ "${PREFIX:-}" == /data/data/com.termux/files/usr ]] || fail 'Execute no Termux normal, sem proot.'
command -v git >/dev/null 2>&1 || fail 'Git ausente.'
if [[ ! -e "$PROJECT" ]]; then
    echo 'Clonando somente a branch selecionada...'
    git clone --single-branch --branch "$BRANCH" "$REPO" "$PROJECT"
fi
[[ -d "$PROJECT/.git" || -f "$PROJECT/.git" ]] || fail "Projeto Git nao encontrado em $PROJECT"
cd "$PROJECT"
case "$(git remote get-url origin)" in
    "$REPO"|https://github.com/dan3850/LASRecomp-Android|git@github.com:dan3850/LASRecomp-Android.git) ;;
    *) fail 'Origin inesperado; o repositorio local nao foi alterado.' ;;
esac
[[ ! -d "$(git rev-parse --git-path rebase-merge)" &&
   ! -d "$(git rev-parse --git-path rebase-apply)" &&
   ! -f "$(git rev-parse --git-path MERGE_HEAD)" &&
   -z "$(git ls-files --unmerged)" ]] || fail 'Merge/rebase pendente. Nada foi removido.'
# Evita perder sobreposicoes: nao aplica stash de uma branch diferente sem revisao.
if ! git diff --quiet || ! git diff --cached --quiet; then
    git status --short
    fail 'Ha alteracoes locais rastreadas. Permanecem intactas; guarde-as antes de atualizar.'
fi

echo
echo '=== Atualizacao segura da branch obrigatoria ==='
git fetch --no-tags origin "refs/heads/$BRANCH"
TARGET="$(git rev-parse FETCH_HEAD)"
git cat-file -e "$RESTORE^{commit}" 2>/dev/null || git fetch --no-tags origin "$RESTORE"
git cat-file -e "$OPTIMIZATION^{commit}" 2>/dev/null || git fetch --no-tags origin "$OPTIMIZATION"
git merge-base --is-ancestor "$RESTORE" "$TARGET" ||
    fail 'Remoto nao descende do commit restaurado. Nada foi mesclado.'
git merge-base --is-ancestor "$OPTIMIZATION" "$TARGET" ||
    fail 'O commit de otimizacao nao esta na branch remota. Interrompido.'
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
    LOCAL_BRANCH="$(git rev-parse "refs/heads/$BRANCH")"
    git merge-base --is-ancestor "$LOCAL_BRANCH" "$TARGET" ||
        fail 'Branch local divergente; sem reset ou mistura de historicos.'
    if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
        git switch "$BRANCH"
    fi
else
    git switch -c "$BRANCH" "$TARGET"
fi
git merge --ff-only "$TARGET"
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail 'Branch incorreta.'
git merge-base --is-ancestor "$OPTIMIZATION" HEAD || fail 'Commit esperado ausente.'
printf 'BRANCH: %s\nHEAD: %s\n' "$BRANCH" "$(git log -1 --format='%h %s')"

# Nunca publicar nem editar a biblioteca recompilada privada do Zelda.
if [[ -z "${LASRECOMP_GAME_SO:-}" ]]; then
    for candidate in \
        "$HOME/lasrecomp-android-gen/build/private-android-lasgame-termux/liblasgame.so" \
        "/storage/emulated/0/Alarms/liblasgame.so"; do
        if [[ -s "$candidate" ]]; then
            export LASRECOMP_GAME_SO="$candidate"
            break
        fi
    done
fi
if [[ -n "${LASRECOMP_GAME_SO:-}" ]]; then
    echo "Biblioteca privada LOCAL: $LASRECOMP_GAME_SO"
else
    echo 'AVISO: liblasgame.so privada nao encontrada; APK podera nao iniciar o jogo.'
fi

echo
echo '=== Compilacao incremental e assinatura ==='
# Compilador do projeto usa os caches existentes e assina com keystore local.
bash "$PROJECT/compilar-lasrecomp-termux.sh"
APK="$PROJECT/build/termux-native/LASRecomp-Android-Termux.apk"
[[ -s "$APK" ]] || fail "APK assinado nao foi gerado: $APK"
mkdir -p "$DEST"
SHORT="$(git rev-parse --short=12 HEAD)"
OUTPUT="$DEST/LASRecomp-eden-GMEM-$SHORT-signed.apk"
cp -f -- "$APK" "$OUTPUT"
echo
echo "BRANCH: $(git branch --show-current)"
echo "HEAD: $(git rev-parse HEAD)"
echo "APK ASSINADO: $OUTPUT"
echo "SHA256: $(sha256sum "$OUTPUT" | cut -d' ' -f1)"
echo "LOG: $PROJECT/build/termux-native/compilacao.log"
