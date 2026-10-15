#!/data/data/com.termux/files/usr/bin/bash
# Compile real user-generated LASRecomp code to an Android ARM64 library,
# using Termux's native Android/Bionic clang. NO Android NDK host toolchain,
# NO PRoot/Linux clang, NO generator re-run and NO game files uploaded.
#
# Run OUTSIDE proot, in Termux:
#   cd ~/lasrecomp-android-gen
#   bash tools/compile-generated-android-termux.sh
#
# The .so contains owner-derived Zelda game code. Do not publish it.
set -euo pipefail

ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/build/gamecode"
OBJ="$ROOT/build/private-android-lasgame-termux/objects"
OUT="$ROOT/build/private-android-lasgame-termux"
LIB="$OUT/liblasgame.so"
ENTRY="$ROOT/tools/gamelib_entry.c"

if [[ "$(uname -m)" != "aarch64" || "\${PREFIX:-}" != /data/data/com.termux/files/usr ]]; then
    echo "ERRO: rode diretamente no Termux ARM64, fora do proot Ubuntu." >&2
    exit 1
fi
command -v clang >/dev/null 2>&1 || { echo "ERRO: clang nao encontrado no Termux." >&2; exit 1; }
command -v llvm-nm >/dev/null 2>&1 || { echo "ERRO: llvm-nm ausente; confira os pacotes llvm/clang do Termux." >&2; exit 1; }
for file in "$SRC/main/main_table.c" "$SRC/sdk/sdk_table.c" "$ENTRY"; do
    [[ -s "$file" ]] || { echo "ERRO: codigo C incompleto: $file" >&2; exit 1; }
done
for folder in main sdk; do
    [[ -s "$SRC/$folder/\${folder}_000.c" ]] || {
        echo "ERRO: faltam os fragmentos do modulo $folder" >&2
        exit 1
    }
done

# Do not start an expensive build with critically low remaining storage.
free_mb="$(df -Pm "$ROOT" | awk 'NR == 2 {print $4}')"
if [[ ! "$free_mb" =~ ^[0-9]+$ || "$free_mb" -lt 3072 ]]; then
    echo "ERRO: menos de 3 GB disponiveis; libere espaco antes de compilar." >&2
    exit 1
fi
mkdir -p "$OBJ"
mapfile -d '' -t SOURCES < <(find "$SRC/main" "$SRC/sdk" -maxdepth 1 -type f -name '*.c' -print0 | sort -z)
SOURCES+=("$ENTRY")
TOTAL="\${#SOURCES[@]}"
if (( TOTAL < 700 )); then
    echo "ERRO: a geracao completa parece ausente ($TOTAL arquivos; esperado >700)." >&2
    exit 1
fi

echo "=== Compilacao nativa Android ARM64 via Termux ==="
echo "Fontes C: $TOTAL (incluindo gamelib_entry.c)"
echo "Espaco disponivel: $free_mb MB"
echo "Objetos: $OBJ"
echo "Compilacao: -O1; um arquivo por vez; continua se for interrompida"
echo

# Both the loader and entry table currently use GAMELIB_ID="dev".
# Changing it here alone causes the APK runtime to reject the library.
CFLAGS=(-std=gnu11 -O1 -g0 -fPIC -fno-strict-aliasing
        -fvisibility=hidden -Wno-unused-label -Wno-return-type
        -I"$ROOT/runtime" '-DGAMELIB_ID="dev"')
OBJECTS=()
N=0
BUILT=0
for src in "\${SOURCES[@]}"; do
    N=$((N+1))
    if [[ "$src" == "$ENTRY" ]]; then
        rel="gamelib_entry.c"
    else
        rel="\${src#"$SRC"/}"
    fi
    obj="$OBJ/\${rel%.c}.o"
    mkdir -p "$(dirname "$obj")"
    if [[ ! -s "$obj" || "$src" -nt "$obj" || "$ROOT/runtime/cpu.h" -nt "$obj" || "$ROOT/runtime/simd.h" -nt "$obj" || "$ROOT/runtime/gamelib.h" -nt "$obj" ]]; then
        echo "[$N/$TOTAL] Compilando $rel"
        # Only replace a completed object; Ctrl+C leaves all prior objects safe.
        clang "\${CFLAGS[@]}" -c "$src" -o "$obj.partial"
        mv -f "$obj.partial" "$obj"
        BUILT=$((BUILT+1))
    elif (( N % 40 == 0 || N == TOTAL )); then
        echo "[$N/$TOTAL] Objetos ja existentes reutilizados"
    fi
    OBJECTS+=("$obj")
done

echo "=== Linkando codigo do Zelda ==="
TMP="$OUT/liblasgame.so.partial"
# Runtime HLE/rt_* symbols intentionally resolve from the application's
# RTLD_GLOBAL liblasrecomp_runtime.so when installed and started. The final
# Android APK loader, ABI and actual boot must still be verified.
clang -shared -Wl,-z,max-page-size=16384 -Wl,-soname,liblasgame.so \
    -Wl,--build-id=sha1 -o "$TMP" "\${OBJECTS[@]}" \
    -llog -landroid -ldl -lm
llvm-nm -D --defined-only "$TMP" | grep -Eq '[[:space:]]lasgame_tables$' || {
    echo "ERRO: biblioteca nao exportou lasgame_tables" >&2
    exit 1
}
mv -f "$TMP" "$LIB"
echo "=== BIBLIOTECA GERADA ==="
ls -lh "$LIB"
echo "Arquivos compilados nesta execucao: $BUILT/$TOTAL"
echo "LOCAL=$LIB"
echo "NOTA: simbolos rt_*/hle_* dependem do runtime do APK; boot ainda nao foi testado."
echo "NAO envie nem publique esta biblioteca derivada do seu jogo."
