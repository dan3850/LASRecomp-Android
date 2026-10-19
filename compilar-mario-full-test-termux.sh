#!/data/data/com.termux/files/usr/bin/bash
# Test branch only: whole main/sdk recompilation, not an APK build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="android/mario-full-recompiler-test"
GAME="${1:-/storage/emulated/0/SwitchRoms/Super-extraido}"
OUT="$ROOT/build/private-mario-full-test"

cd "$ROOT"
if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
    echo "ERRO: este teste exige a branch $BRANCH; nenhuma branch foi trocada." >&2
    exit 1
fi
if [[ "$(uname -m)" != aarch64 || "${PREFIX:-}" != /data/data/com.termux/files/usr ]]; then
    echo "ERRO: execute no Termux ARM64, fora do proot." >&2
    exit 1
fi
for tool in python3 clang llvm-nm; do
    command -v "$tool" >/dev/null || { echo "ERRO: comando ausente: $tool" >&2; exit 1; }
done
python3 - <<'PY'
import importlib.util
missing = [m for m in ('capstone', 'unicorn', 'lz4') if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit('ERRO: modulos Python ausentes: ' + ', '.join(missing) +
                     '. Reutilize os pacotes Python/Termux ja usados nos testes do Mario.')
PY

mkdir -p "$OUT"
echo "BRANCH=$(git branch --show-current)"
echo "HEAD=$(git rev-parse HEAD)"
echo "JOGO=$GAME"
echo "SAIDA=$OUT"
echo "=== TESTES DO GERADOR COMPLETO ==="
python3 -m unittest discover -s tests -p test_mario_full_recompiler.py -v
echo "=== GERANDO E COMPILANDO MAIN/SDK ==="
python3 -u tools/mario_full_recompile.py "$GAME" --compile --simd asm \
    --jobs "${MARIO_JOBS:-2}" --output "$OUT" 2>&1 | tee "$OUT/compilacao.log"
echo "BRANCH=$(git branch --show-current)"
echo "HEAD=$(git rev-parse HEAD)"
echo "BIBLIOTECA=$OUT/libmario_test.so"
echo "RELATORIO=$OUT/build-report.json"
echo "LOG=$OUT/compilacao.log"
echo "Biblioteca experimental main/sdk; a integracao de boot Android e uma etapa seguinte."
