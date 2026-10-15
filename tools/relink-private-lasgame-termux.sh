#!/data/data/com.termux/files/usr/bin/bash
# Re-link the owner's ALREADY COMPILED 719 Zelda objects against the Android
# runtime. No recompilation, no NSO re-extraction, no upload of game code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/private-android-lasgame-termux"
LIB="$OUT/liblasgame.so"
OBJ="$OUT/objects"
RUNTIME_DIR="$OUT/runtime-link"
RUNTIME="$RUNTIME_DIR/liblasrecomp_runtime.so"
NEW_LIB="$OUT/liblasgame.so.relinked.partial"
DOWNLOAD="/storage/emulated/0/Download/liblasgame.so"

if [[ "$(uname -m)" != "aarch64" || "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]]; then
    echo "ERRO: rode diretamente no Termux ARM64, fora do Ubuntu/proot." >&2
    exit 1
fi
for cmd in python3 clang llvm-nm llvm-readelf; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERRO: falta a ferramenta $cmd no Termux." >&2
        exit 1
    }
done
[[ -s "$LIB" && -d "$OBJ" ]] || {
    echo "ERRO: nao encontrei a lib original ou os objetos. Nao alterei nada." >&2
    exit 1
}

APK="${1:-}"
if [[ -z "$APK" ]]; then
    APK="$(python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile, BadZipFile
found = []
for p in Path("/storage/emulated/0/Download").glob("*.apk"):
    try:
        with ZipFile(p) as z:
            entries = set(z.namelist())
            if {"lib/arm64-v8a/liblasrecomp_runtime.so",
                "lib/arm64-v8a/liblasrecomp_prepare.so",
                "lib/arm64-v8a/libSDL3.so"} <= entries:
                found.append(p)
    except (OSError, BadZipFile):
        pass
if found:
    print(max(found, key=lambda p: p.stat().st_mtime))
PY
)"
fi
[[ -n "$APK" && -f "$APK" ]] || {
    echo "ERRO: APK com o motor nao encontrado em Downloads." >&2
    echo "Informe o caminho do APK como argumento para este script." >&2
    exit 1
}

mkdir -p "$RUNTIME_DIR"
python3 - "$APK" "$RUNTIME" <<'PY'
from pathlib import Path
from zipfile import ZipFile
import shutil, sys
apk, runtime = Path(sys.argv[1]), Path(sys.argv[2])
with ZipFile(apk) as z:
    with z.open("lib/arm64-v8a/liblasrecomp_runtime.so") as source:
        with runtime.open("wb") as dest:
            shutil.copyfileobj(source, dest, 1024 * 1024)
if runtime.stat().st_size < 1024:
    raise SystemExit("ERRO: motor extraido incompleto")
print("Motor Android encontrado:", apk, flush=True)
PY

# Do not use grep -q under pipefail: llvm-nm could receive SIGPIPE.
llvm-nm -D --defined-only "$RUNTIME" | awk '
    $NF == "g_fnprof" { found=1 }
    END { exit !found }
' || {
    echo "ERRO: motor do APK nao exporta g_fnprof. Original preservado." >&2
    exit 1
}

mapfile -d '' -t OBJECTS < <(find "$OBJ" -type f -name '*.o' -print0 | sort -z)
if (( ${#OBJECTS[@]} != 719 )); then
    echo "ERRO: encontrei ${#OBJECTS[@]} objetos, esperava 719. Original preservado." >&2
    exit 1
fi

echo "=== LINK NOVO: 719 objetos reutilizados; nenhum arquivo C recompilado ==="
# Direct DT_NEEDED reference resolves g_fnprof/other runtime symbols in
# Android's app linker namespace, unlike a standalone RTLD_GLOBAL load.
clang -shared -Wl,-z,max-page-size=16384 -Wl,-soname,liblasgame.so \
    -Wl,--build-id=sha1 -Wl,--no-undefined -o "$NEW_LIB" \
    "${OBJECTS[@]}" \
    -Wl,--no-as-needed -L"$RUNTIME_DIR" -llasrecomp_runtime \
    -llog -landroid -ldl -lm

# Check actual exports AND declared dependency before touching original.
llvm-nm -D --defined-only "$NEW_LIB" | awk '
    $NF == "lasgame_tables" { found=1 }
    END { exit !found }
' || {
    echo "ERRO: resultado nao exporta lasgame_tables. Original preservado." >&2
    exit 1
}
llvm-readelf -d "$NEW_LIB" | grep -F 'liblasrecomp_runtime.so' >/dev/null || {
    echo "ERRO: resultado nao depende diretamente do motor. Original preservado." >&2
    exit 1
}

BACKUP="$OUT/liblasgame.so.before-runtime-link"
if [[ ! -e "$BACKUP" ]]; then
    cp -p "$LIB" "$BACKUP"
fi
mv -f "$NEW_LIB" "$LIB"
echo "=== BIBLIOTECA RELIGADA E VERIFICADA ==="
ls -lh "$LIB" "$BACKUP"
cp -f "$LIB" "$DOWNLOAD"
echo "OK: $DOWNLOAD"
echo "No LASRecomp Local TESTE, importe novamente a liblasgame.so e toque VERIFICAR."
echo "Nenhum arquivo do Zelda foi enviado ao GitHub."
