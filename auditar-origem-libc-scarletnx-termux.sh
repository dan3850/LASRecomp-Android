#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
BUILD="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
TARGET="$BUILD/src/gui/libmain.so"
REPORT="$HOME/storage/downloads/ScarletNX-origem-libc.txt"
mkdir -p "$(dirname "$REPORT")"
exec > >(tee "$REPORT") 2>&1
echo "SCARLETNX_ORIGEM_LIBC"
[[ -s "$TARGET" && -s "$BUILD/scarletnx-ndk-relink-command.sh" ]] || { echo "ERRO: build/comando anterior ausente"; exit 2; }
python3 - "$BUILD" <<'PY'
import pathlib,sys,shlex
build=pathlib.Path(sys.argv[1])
p=build/'scarletnx-ndk-relink-command.sh'
line=p.read_text().splitlines()[-1]
parts=shlex.split(line)
indices=[i for i,x in enumerate(parts) if x.endswith('/clang++')]
if len(indices)!=1: raise SystemExit('ERRO: driver ambiguo')
i=indices[0]
parts[i+1:i+1]=['-Wl,--trace-symbol=getauxval','-Wl,--trace-symbol=__libc_init',f'-Wl,-Map={build}/scarletnx-link-map.txt']
(build/'scarletnx-trace-command.sh').write_text('#!/bin/sh\n'+shlex.join(parts)+'\n')
PY
BACKUP="$TARGET.before-origin-audit"
cp -f "$TARGET" "$BACKUP"
restore() { cp -f "$BACKUP" "$TARGET"; }
trap restore EXIT
echo "=== LINK TRACE ==="
(cd "$BUILD" && bash scarletnx-trace-command.sh) 2>&1 | tail -150 || true
echo "=== MAP SYMBOL CONTEXT ==="
MAP="$BUILD/scarletnx-link-map.txt"
if [[ -s "$MAP" ]]; then
  grep -n -B 9 -A 5 -E '(^|[[:space:]])(getauxval|__libc_init)([[:space:]]|$)' "$MAP" | head -170 || true
  echo "=== MAP ARCHIVE INCLUSION ==="
  sed -n '1,110p' "$MAP"
else
  echo "LINK_MAP_MISSING"
fi
echo "=== STATIC ARCHIVE DEFINITIONS (bounded search) ==="
find "$BUILD" "$ROOT/android-llvm" -type f \( -name '*.a' -o -name '*.o' \) -print0 2>/dev/null |
  xargs -0 -r -n 1 -P 2 sh -c '
    out=$(llvm-nm -A --defined-only "$0" 2>/dev/null | grep -E " [TW] (getauxval|__libc_init)$" | head -4)
    [ -z "$out" ] || printf "%s\n" "$out"
  ' | head -70 || true
echo "ORIGIN_AUDIT_COMPLETE"
