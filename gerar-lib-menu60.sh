#!/data/data/com.termux/files/usr/bin/bash
# Produce a menu-compatible game library locally; never modify the original
# NSO, generated C, object cache or game library.
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${LASRECOMP_WORKSPACE:-$HOME/lasrecomp-android-gen}"
OUTPUT="${LASRECOMP_MODS_OUTPUT:-/storage/emulated/0/Download/LASRecomp/Mods-menu/liblasgame.so}"

[[ "$(uname -m)" == aarch64 && "${PREFIX:-}" == /data/data/com.termux/files/usr ]] || {
    echo 'ERRO: execute no Termux ARM64, fora do proot.' >&2; exit 1;
}
[[ -d "$WORKSPACE/build/gamecode/main" ]] || {
    echo "ERRO: codigo privado do jogo nao encontrado: $WORKSPACE/build/gamecode/main" >&2; exit 1;
}
command -v llvm-nm >/dev/null || { echo 'ERRO: instale llvm no Termux.' >&2; exit 1; }

ORIGINAL="$WORKSPACE/build/private-android-lasgame-termux/liblasgame.so"
mkdir -p "$(dirname "$OUTPUT")"
if [[ -s "$ORIGINAL" ]] && llvm-nm -D --defined-only "$ORIGINAL" 2>/dev/null | grep -Eq '[[:space:]]lasgame_mod_menu_v1$'; then
    # The updated generator has already produced the selectable variant.
    [[ "$(realpath "$ORIGINAL")" != "$(realpath -m "$OUTPUT")" ]] || {
        echo 'ERRO: destino nao pode substituir a biblioteca original.' >&2; exit 1;
    }
    cp -L "$ORIGINAL" "$OUTPUT"
else
    # For an existing, unchanged generated library, compile only the two
    # affected chunks and link a separate selectable library.
    python3 "$PROJECT/tools/apply-stable60-mod.py" \
        --workspace "$WORKSPACE" --menu-compatible --copy-to "$OUTPUT" "$@"
fi

[[ -s "$OUTPUT" ]] || { echo 'ERRO: a biblioteca nao foi produzida.' >&2; exit 1; }
llvm-nm -D --defined-only "$OUTPUT" | grep -Eq '[[:space:]]lasgame_mod_menu_v1$' || {
    echo 'ERRO: biblioteca sem suporte ao menu MODS.' >&2; exit 1;
}
printf '\nBIBLIOTECA PRONTA: %s\n' "$OUTPUT"
printf 'No Android: importar codigo do jogo > escolher esta liblasgame.so > MODS > ativar Stable 60fps v2.\n'
printf 'O mod comeca desligado e sua escolha entra em vigor ao reiniciar o jogo.\n'