#!/data/data/com.termux/files/usr/bin/bash
# Fast, private fix for Android linker lookup of g_fnprof/rt_* HLE functions.
# Re-links ALREADY BUILT owner-generated object files, without compiling again,
# uploading any Zelda content, running proot, or touching the extracted NSOs.
# Usage (Termux, outside proot):
#   bash tools/relink-private-lasgame-termux.sh [path/to/LASRecomp-Android.apk]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/private-android-lasgame-termux"
LIB="$OUT/liblasgame.so"
OBJ="$OUT/objects"
RUNTIME_DIR="$OUT/runtime-link"
RUNTIME="$RUNTIME_DIR/liblasrecomp_runtime.so"
NEW_LIB="$OUT/liblasgame.so.relinked.partial"

if [[ "$(uname -m)" != "aarch64" || "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]]; then
    echo "ERRO: execute no Termux ARM64 normal (nao no Ubuntu/proot)." >&2
    exit 1
fi
for cmd in python3 clang llvm-nm; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "ERRO: ferramenta $cmd ausente no Termux." >&2; exit 1;
    }
done
[[ -s "$LIB" && -d "$OBJ" ]] || {
    echo "ERRO: liblasgame.so ou objetos compilados ausentes. Nenhum arquivo foi alterado." >&2
    exit 1
}

APK="${1:-}"
if [[ -z "$APK" ]]; then
    # Find a previously downloaded, genuine LASRecomp runtime APK on-device.
    # We do not download or rebuild anything.
    APK="$(python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile, BadZipFile
root = Path('/storage/emulated/0/Download')
found = []
for p in root.glob('*.apk'):
    try:
        with ZipFile(p) as z:
            names = set(z.namelist())
            if ('lib/arm64-v8a/liblasrecomp_runtime.so' in names
                and 'lib/arm64-v8a/liblasrecomp_prepare.so' in names
                and 'lib/arm64-v8a/libSDL3.so' in names):
                found.append(p)
    except (OSError, BadZipFile):
        pass
if found:
    print(max(found, key=lambda p: p.stat().st_mtime))
PY
)"
fi
[[ -n "$APK" && -f "$APK" ]] || {
    echo "ERRO: nao achei APK do LASRecomp em Downloads." >&2
    echo "Passe seu APK de teste como argumento: bash tools/relink-private-lasgame-termux.sh /sdcard/Download/arquivo.apk" >&2
    exit 1
}

mkdir -p "$RUNTIME_DIR"
python3 - "$APK" "$RUNTIME" <<'PY'
from pathlib import Path
from zipfile import ZipFile
import shutil, sys
apk, dst = Path(sys.argv[1]), Path(sys.argv[2])
with ZipFile(apk) as z:
    name = 'lib/arm64-v8a/liblasrecomp_runtime.so'
    with z.open(name) as inp, dst.open('wb') as out:
        shutil.copyfileobj(inp, out, 1024 * 1024)
if dst.stat().st_size < 1024:
    raise SystemExit('ERRO: motor extraido do APK esta incompleto')
print('Motor Android extraido do APK:', apk, flush=True)
PY

llvm-nm -D --defined-only "$RUNTIME" | grep -E '[[:space:]]g_fnprof || {
    echo "ERRO: motor Android deste APK nao exporta g_fnprof. Nada alterado." >&2
    exit 1
}
mapfile -d '' -t OBJECTS < <(find "$OBJ" -type f -name '*.o' -print0 | sort -z)
if (( ${#OBJECTS[@]} != 719 )); then
    echo "ERRO: esperado 719 objetos; achei ${#OBJECTS[@]}. Nao vou regenerar nem sobrescrever a .so." >&2
    exit 1
fi

echo "=== Corrigindo apenas a ligacao (0 arquivos C recompilados) ==="
echo "Objetos reutilizados: ${#OBJECTS[@]}"
echo "APK base: $APK"
echo "Biblioteca original preservada ate validar a nova."

# Force a direct ELF DT_NEEDED edge to the actual runtime SONAME; relying on
# RTLD_GLOBAL alone did not work on the tested Android linker namespace.
# --no-undefined catches the NEXT missing symbol locally, not in a phone run.
clang -shared -Wl,-z,max-page-size=16384 \
    -Wl,-soname,liblasgame.so -Wl,--build-id=sha1 \
    -Wl,--no-undefined -o "$NEW_LIB" "${OBJECTS[@]}" \
    -Wl,--no-as-needed -L"$RUNTIME_DIR" -llasrecomp_runtime \
    -llog -landroid -ldl -lm

llvm-nm -D --defined-only "$NEW_LIB" | grep -E '[[:space:]]lasgame_tables || {
    echo "ERRO: arquivo novo nao exporta lasgame_tables. Original intacto." >&2
    exit 1
}
if command -v llvm-readelf >/dev/null 2>&1; then
    llvm-readelf -d "$NEW_LIB" | grep -q 'liblasrecomp_runtime.so' || {
        echo "ERRO: ELF nao possui dependencia direta do motor. Original intacto." >&2
        exit 1
    }
fi

# Keep a single known-good backup; never delete it or overwrite on retry.
if [[ ! -e "$OUT/liblasgame.so.before-runtime-link" ]]; then
    cp -p "$LIB" "$OUT/liblasgame.so.before-runtime-link"
fi
mv -f "$NEW_LIB" "$LIB"
echo "=== LINK CORRIGIDO ==="
ls -lh "$LIB" "$OUT/liblasgame.so.before-runtime-link"
echo "Atualizando copia na pasta Download para importar novamente no aplicativo..."
cp -f "$LIB" "/storage/emulated/0/Download/liblasgame.so"
echo "OK: /storage/emulated/0/Download/liblasgame.so"
echo "NENHUM arquivo do jogo foi enviado ao GitHub."
echo "No app LASRecomp Local TESTE: importar novamente liblasgame.so e tocar VERIFICAR."
 >/dev/null || {
    echo "ERRO: motor Android deste APK nao exporta g_fnprof. Nada alterado." >&2
    exit 1
}
mapfile -d '' -t OBJECTS < <(find "$OBJ" -type f -name '*.o' -print0 | sort -z)
if (( ${#OBJECTS[@]} != 719 )); then
    echo "ERRO: esperado 719 objetos; achei ${#OBJECTS[@]}. Nao vou regenerar nem sobrescrever a .so." >&2
    exit 1
fi

echo "=== Corrigindo apenas a ligacao (0 arquivos C recompilados) ==="
echo "Objetos reutilizados: ${#OBJECTS[@]}"
echo "APK base: $APK"
echo "Biblioteca original preservada ate validar a nova."

# Force a direct ELF DT_NEEDED edge to the actual runtime SONAME; relying on
# RTLD_GLOBAL alone did not work on the tested Android linker namespace.
# --no-undefined catches the NEXT missing symbol locally, not in a phone run.
clang -shared -Wl,-z,max-page-size=16384 \
    -Wl,-soname,liblasgame.so -Wl,--build-id=sha1 \
    -Wl,--no-undefined -o "$NEW_LIB" "${OBJECTS[@]}" \
    -Wl,--no-as-needed -L"$RUNTIME_DIR" -llasrecomp_runtime \
    -llog -landroid -ldl -lm

llvm-nm -D --defined-only "$NEW_LIB" | grep -Eq '[[:space:]]lasgame_tables$' || {
    echo "ERRO: arquivo novo nao exporta lasgame_tables. Original intacto." >&2
    exit 1
}
if command -v llvm-readelf >/dev/null 2>&1; then
    llvm-readelf -d "$NEW_LIB" | grep -q 'liblasrecomp_runtime.so' || {
        echo "ERRO: ELF nao possui dependencia direta do motor. Original intacto." >&2
        exit 1
    }
fi

# Keep a single known-good backup; never delete it or overwrite on retry.
if [[ ! -e "$OUT/liblasgame.so.before-runtime-link" ]]; then
    cp -p "$LIB" "$OUT/liblasgame.so.before-runtime-link"
fi
mv -f "$NEW_LIB" "$LIB"
echo "=== LINK CORRIGIDO ==="
ls -lh "$LIB" "$OUT/liblasgame.so.before-runtime-link"
echo "Atualizando copia na pasta Download para importar novamente no aplicativo..."
cp -f "$LIB" "/storage/emulated/0/Download/liblasgame.so"
echo "OK: /storage/emulated/0/Download/liblasgame.so"
echo "NENHUM arquivo do jogo foi enviado ao GitHub."
echo "No app LASRecomp Local TESTE: importar novamente liblasgame.so e tocar VERIFICAR."
 >/dev/null || {
    echo "ERRO: arquivo novo nao exporta lasgame_tables. Original intacto." >&2
    exit 1
}
if command -v llvm-readelf >/dev/null 2>&1; then
    llvm-readelf -d "$NEW_LIB" | grep -q 'liblasrecomp_runtime.so' || {
        echo "ERRO: ELF nao possui dependencia direta do motor. Original intacto." >&2
        exit 1
    }
fi

# Keep a single known-good backup; never delete it or overwrite on retry.
if [[ ! -e "$OUT/liblasgame.so.before-runtime-link" ]]; then
    cp -p "$LIB" "$OUT/liblasgame.so.before-runtime-link"
fi
mv -f "$NEW_LIB" "$LIB"
echo "=== LINK CORRIGIDO ==="
ls -lh "$LIB" "$OUT/liblasgame.so.before-runtime-link"
echo "Atualizando copia na pasta Download para importar novamente no aplicativo..."
cp -f "$LIB" "/storage/emulated/0/Download/liblasgame.so"
echo "OK: /storage/emulated/0/Download/liblasgame.so"
echo "NENHUM arquivo do jogo foi enviado ao GitHub."
echo "No app LASRecomp Local TESTE: importar novamente liblasgame.so e tocar VERIFICAR."
 >/dev/null || {
    echo "ERRO: motor Android deste APK nao exporta g_fnprof. Nada alterado." >&2
    exit 1
}
mapfile -d '' -t OBJECTS < <(find "$OBJ" -type f -name '*.o' -print0 | sort -z)
if (( ${#OBJECTS[@]} != 719 )); then
    echo "ERRO: esperado 719 objetos; achei ${#OBJECTS[@]}. Nao vou regenerar nem sobrescrever a .so." >&2
    exit 1
fi

echo "=== Corrigindo apenas a ligacao (0 arquivos C recompilados) ==="
echo "Objetos reutilizados: ${#OBJECTS[@]}"
echo "APK base: $APK"
echo "Biblioteca original preservada ate validar a nova."

# Force a direct ELF DT_NEEDED edge to the actual runtime SONAME; relying on
# RTLD_GLOBAL alone did not work on the tested Android linker namespace.
# --no-undefined catches the NEXT missing symbol locally, not in a phone run.
clang -shared -Wl,-z,max-page-size=16384 \
    -Wl,-soname,liblasgame.so -Wl,--build-id=sha1 \
    -Wl,--no-undefined -o "$NEW_LIB" "${OBJECTS[@]}" \
    -Wl,--no-as-needed -L"$RUNTIME_DIR" -llasrecomp_runtime \
    -llog -landroid -ldl -lm

llvm-nm -D --defined-only "$NEW_LIB" | grep -Eq '[[:space:]]lasgame_tables$' || {
    echo "ERRO: arquivo novo nao exporta lasgame_tables. Original intacto." >&2
    exit 1
}
if command -v llvm-readelf >/dev/null 2>&1; then
    llvm-readelf -d "$NEW_LIB" | grep -q 'liblasrecomp_runtime.so' || {
        echo "ERRO: ELF nao possui dependencia direta do motor. Original intacto." >&2
        exit 1
    }
fi

# Keep a single known-good backup; never delete it or overwrite on retry.
if [[ ! -e "$OUT/liblasgame.so.before-runtime-link" ]]; then
    cp -p "$LIB" "$OUT/liblasgame.so.before-runtime-link"
fi
mv -f "$NEW_LIB" "$LIB"
echo "=== LINK CORRIGIDO ==="
ls -lh "$LIB" "$OUT/liblasgame.so.before-runtime-link"
echo "Atualizando copia na pasta Download para importar novamente no aplicativo..."
cp -f "$LIB" "/storage/emulated/0/Download/liblasgame.so"
echo "OK: /storage/emulated/0/Download/liblasgame.so"
echo "NENHUM arquivo do jogo foi enviado ao GitHub."
echo "No app LASRecomp Local TESTE: importar novamente liblasgame.so e tocar VERIFICAR."
