#!/usr/bin/env bash
# Testa as tres correcoes de shaders do ScarletNX sem tocar no checkout principal.
set -euo pipefail
BASE="${1:-${SCARLETNX_SRC:-}}"
if [[ -z "$BASE" || ! -d "$BASE/.git" && ! -f "$BASE/.git" ]]; then
  echo "Uso: $0 /caminho/para/ScarletNX (checkout Git do ScarletNX)" >&2
  exit 2
fi
BASE="$(cd "$BASE" && pwd)"
if [[ -n "$(git -C "$BASE" status --porcelain)" ]]; then
  echo "ERRO: checkout ScarletNX com alteracoes locais. Nada modificado." >&2
  exit 2
fi
PIN="34853eeae5af132e320adbb0193f13344085bf89"
COMMITS=(
  92fbbfa328140424c03c74f66800d3c210425b0e
  4149dd90e562810a55856136c58aabb26b697a5b
  1ac8360b66096060146915ed1f17ab20a28458ae
)
if [[ "$(git -C "$BASE" rev-parse HEAD)" != "$PIN" ]]; then
  echo "ERRO: ScarletNX nao esta no commit base esperado $PIN. Nada modificado." >&2
  exit 2
fi
TMP="$(mktemp -d)"
cleanup() {
  git -C "$BASE" worktree remove --force "$TMP/worktree" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
git -C "$BASE" fetch --no-tags https://github.com/scarletnx/ScarletNX.git "${COMMITS[@]}"
git -C "$BASE" worktree add --detach "$TMP/worktree" "$PIN" >/dev/null
for commit in "${COMMITS[@]}"; do
  echo "Testando $commit"
  if ! git -C "$TMP/worktree" cherry-pick --no-commit "$commit"; then
    git -C "$TMP/worktree" cherry-pick --abort >/dev/null 2>&1 || true
    echo "INCOMPATIVEL: conflito em $commit; precisa de adaptacao manual. Nenhum codigo publicado." >&2
    exit 1
  fi
  git -C "$TMP/worktree" -c user.name=ShaderAudit -c user.email=shader-audit@localhost commit -qm "audit: upstream shader $commit"
done
git -C "$TMP/worktree" diff --binary "$PIN" HEAD > "$BASE/../scarletnx-shader-three-fixes.patch"
echo "Patch gerado: $BASE/../scarletnx-shader-three-fixes.patch"
echo "ATENCAO: patch ainda precisa de testes de compilacao e regressao antes de usar no APK."
