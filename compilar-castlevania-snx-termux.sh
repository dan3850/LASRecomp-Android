#!/data/data/com.termux/files/usr/bin/bash
# Castlevania AOT -> ScarletNX Android runtime, reusing the working Mario build.
# No recompilation of the game's 1,152 AOT blocks and no cache cleaning.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = experimental/castlevania-belmonts-curse ] || {
  echo "ERRO: selecione experimental/castlevania-belmonts-curse" >&2
  exit 1
}
ID=0100BA4026E94000
export CASTLEVANIA_SNX_CODE_SO="${CASTLEVANIA_SNX_CODE_SO:-/storage/emulated/0/Download/$ID/${ID}_code.so}"
[ -s "$CASTLEVANIA_SNX_CODE_SO" ] || {
  echo "ERRO: modulo recompilado nao encontrado: $CASTLEVANIA_SNX_CODE_SO" >&2
  echo "Exporte o _code.so do ScarletNX para Download, ou defina CASTLEVANIA_SNX_CODE_SO." >&2
  exit 1
}
command -v llvm-readelf >/dev/null || { echo "Falta llvm-readelf" >&2; exit 1; }
command -v llvm-nm >/dev/null || { echo "Falta llvm-nm" >&2; exit 1; }
llvm-readelf -h "$CASTLEVANIA_SNX_CODE_SO" | grep -F 'AArch64' >/dev/null || {
  echo "ERRO: codigo AOT nao e ELF AArch64" >&2; exit 1;
}
# Read the whole symbol table before matching: no grep -q/SIGPIPE.
symbols="$(mktemp)"
trap 'rm -f "$symbols"' EXIT
llvm-nm -D --defined-only "$CASTLEVANIA_SNX_CODE_SO" > "$symbols"
grep -E '[[:space:]]snx_module$' "$symbols" >/dev/null || {
  echo "ERRO: falta a entrada snx_module, ou ABI ScarletNX incompativel" >&2; exit 1;
}
abi="$(dirname "$CASTLEVANIA_SNX_CODE_SO")/$ID.abi"
if [ -s "$abi" ] && [ "$(cat "$abi")" != 12 ]; then
  echo "ERRO: modulo declara ABI diferente de 12; nao misturar recompiladores." >&2
  exit 1
fi
echo "CASTLEVANIA_AOT_READY: $CASTLEVANIA_SNX_CODE_SO"
echo "Usando runtime ScarletNX existente, sem extrair nem copiar o XCI para dentro do APK."
bash "$ROOT/compilar-mario-snx-runtime-termux.sh"
