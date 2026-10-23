#!/data/data/com.termux/files/usr/bin/bash
# Zelda: Link's Awakening — ScarletNX + Ryujinx NativeAOT (Termux).
# Keeps Castlevania and the previous Zelda APK untouched.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = experimental/zelda-links-awakening-ryujinx-nativeaot ] || {
  echo "ERRO: selecione a branch experimental/zelda-links-awakening-ryujinx-nativeaot" >&2
  exit 1
}
export ZELDA_SNX_CODE_SO="${ZELDA_SNX_CODE_SO:-/storage/emulated/0/Download/ZeldaRecomp/01006BB00C6F0000/01006BB00C6F0000_code.so}"
[ -s "$ZELDA_SNX_CODE_SO" ] || { echo "ERRO: Zelda code.so nao encontrado: $ZELDA_SNX_CODE_SO" >&2; exit 1; }
echo "Zelda AOT: $ZELDA_SNX_CODE_SO"
bash "$ROOT/compilar-castlevania-ryujinx-nativo-termux.sh" "$@"
