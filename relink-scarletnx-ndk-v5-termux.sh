#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
BUILD="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
NDK="$HOME/android-sdk/ndk/28.2.13676358"
TARGET="$BUILD/src/gui/libmain.so"
REPORT="$HOME/storage/downloads/ScarletNX-relink-ndk-v5.txt"
mkdir -p "$(dirname "$REPORT")"
[[ -s "$TARGET" && -s "$BUILD/scarletnx-relink-v4.sh" ]] || { echo "ERRO: arquivos da V4 ausentes"; exit 2; }
python3 - "$BUILD" "$NDK" <<'PY'
import pathlib,sys,shlex
build=pathlib.Path(sys.argv[1]); ndk=pathlib.Path(sys.argv[2])
src=build/'scarletnx-relink-v4.sh'
args=shlex.split(src.read_text().splitlines()[-1])
if args[0]!='exec': raise SystemExit('Unexpected V4 command')
args=args[1:]
candidates=[
ndk/'toolchains/llvm/prebuilt/linux-x86_64/lib/clang/19/lib/linux/libunwind.a',
ndk/'toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libunwind.a',
ndk/'toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33/libunwind.a',
pathlib.Path('/data/data/com.termux/files/usr/lib/clang/21/lib/linux/libunwind.a')]
unwind=next((p for p in candidates if p.is_file()),None)
if unwind is None: raise SystemExit('ERRO: libunwind.a nao encontrada. Nada modificado.')
print('UNWIND_RUNTIME='+str(unwind))
# Insert before the final shared libc and crtend; static archives are resolved left-to-right.
crtend=next((i for i,x in enumerate(args) if x.endswith('/crtend_so.o')),None)
if crtend is None: raise SystemExit('Missing crtend')
args.insert(crtend-1,str(unwind))
(build/'scarletnx-relink-v5.sh').write_text('#!/bin/sh\nexec '+shlex.join(args)+'\n')
PY
BACKUP="$TARGET.before-ndk-v5"
cp -f "$TARGET" "$BACKUP"
trap 'cp -f "$BACKUP" "$TARGET"' EXIT
{
 echo SCARLETNX_RELINK_NDK_V5
 set +e
 (cd "$BUILD" && sh scarletnx-relink-v5.sh)
 status=$?
 set -e
 echo "LINK_EXIT=$status"
 if [[ "$status" == 0 ]]; then
  echo '=== NEEDED ==='
  readelf -d "$TARGET" | grep NEEDED || true
  echo '=== SYMBOLS ==='
  readelf -Ws "$TARGET" | grep -E ' (getauxval|__libc_init)$' | head -12 || true
  if readelf -d "$TARGET" | grep -q 'NEEDED.*libc[.]so' && ! readelf -Ws "$TARGET" | awk '$7 != "UND" && ($8=="getauxval" || $8=="__libc_init") {found=1} END{exit !found}'; then
   echo RELINK_V5_VALIDATED
  else echo RELINK_V5_INVALID; fi
 fi
 echo ORIGINAL_RESTORED_ON_EXIT
} > "$REPORT" 2>&1
echo "RELATORIO_GERADO=$REPORT"
