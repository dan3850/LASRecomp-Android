#!/data/data/com.termux/files/usr/bin/bash
# Opt-in Zelda Stable60 Home toggle. Never replaces the proven DejaVu APK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests -p 'test_scarletnx_zelda60_toggle.py'
test "$(git branch --show-current)" = "experimental/zelda-links-awakening-ryujinx-nativeaot" || {
  echo "ERRO: selecione a branch experimental/zelda-links-awakening-ryujinx-nativeaot" >&2
  exit 1
}
FOLDER="/storage/emulated/0/Download/ZeldaRecomp"
GOOD="$FOLDER/Zelda-SNX-Runtime-DEJAVU-TESTE.apk"
BACKUP="$FOLDER/Zelda-SNX-Runtime-BOOT-OK-ANTES-FPS.apk"
mkdir -p "$FOLDER"
if [ -s "$GOOD" ] && [ ! -e "$BACKUP" ]; then
  cp -p "$GOOD" "$BACKUP"
  echo "APK com boot preservado: $BACKUP"
fi

# This MUST be the separately recompiled AOT, not the old 251 MB library.
export ZELDA_SNX_CODE_SO="${ZELDA_SNX_CODE_SO:-$FOLDER/Stable60AOT/01006BB00C6F0000_code.so}"
test -s "$ZELDA_SNX_CODE_SO" || {
  echo "ERRO: AOT Stable60 ainda nao gerado: $ZELDA_SNX_CODE_SO" >&2
  exit 1
}
command -v llvm-readelf >/dev/null || { echo "ERRO: llvm-readelf ausente" >&2; exit 1; }
if ! llvm-readelf -W --dyn-syms "$ZELDA_SNX_CODE_SO" |
     grep -F "snx_zelda_stable60_enabled" >/dev/null; then
  echo "ERRO: biblioteca AOT sem o simbolo snx_zelda_stable60_enabled." >&2
  echo "Recompile primeiro o jogo com SNX_ZELDA60_AOT=1 e patch --mode aot." >&2
  exit 1
fi

export SCARLETNX_ZELDA60_TOGGLE=1
echo "Stable60: AOT verificado; compilando runtime Home toggle em APK separado."
bash "$ROOT/compilar-zelda-ryujinx-termux.sh"
test -s "$FOLDER/Zelda-SNX-Runtime-STABLE60-TOGGLE-TESTE.apk"
echo "===== TESTE STABLE60 PRONTO ====="
echo "$FOLDER/Zelda-SNX-Runtime-STABLE60-TOGGLE-TESTE.apk"
echo "Home > Stable 60 FPS: OFF (original) / ON (mod)."
echo "A versao BOOT-OK permanece preservada."
