#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
BUILD="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
NDK="$HOME/android-sdk/ndk/28.2.13676358"
SYS="$NDK/toolchains/llvm/prebuilt/sysroot"
API="$SYS/usr/lib/aarch64-linux-android/24"
CXX="$SYS/usr/lib/aarch64-linux-android"
RT="$NDK/toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33"
TARGET="$BUILD/src/gui/libmain.so"
REPORT="$HOME/storage/downloads/ScarletNX-relink-corrigido.txt"
mkdir -p "$(dirname "$REPORT")"
[[ -s "$TARGET" && -s "$BUILD/build.ninja" ]] || { echo "Build nativa nao encontrada"; exit 2; }
for f in "$API/crtbegin_so.o" "$API/crtend_so.o" "$API/libc.so" "$CXX/libc++_shared.so"; do [[ -s "$f" ]] || { echo "Arquivo NDK ausente: $f"; exit 2; }; done
python3 - "$BUILD" "$API" "$CXX" "$RT" <<'PY'
import pathlib,sys,subprocess,shlex
build,api,cxx,rt=sys.argv[1:]
r=subprocess.run(['ninja','-C',build,'-t','commands','src/gui/libmain.so'],capture_output=True,text=True)
if r.returncode: raise SystemExit(r.stderr)
lines=[x for x in r.stdout.splitlines() if ' -o src/gui/libmain.so ' in x and 'clang++' in x]
if len(lines)!=1: raise SystemExit(f'Expected 1 link command, got {len(lines)}')
line=lines[0].strip()
if not (line.startswith(': && ') and line.endswith(' && :')):
 raise SystemExit('Unexpected ninja shell wrapper')
command=line[len(': && '):-len(' && :')]
args=shlex.split(command)
if not args[0].endswith('clang++'): raise SystemExit('Unexpected compiler')
# NDK crt must precede objects. No implicit Termux CRT/libc or static compiler runtime.
args[1:1]=['-nostdlib',f'{api}/crtbegin_so.o','-Wl,--trace-symbol=getauxval','-Wl,--trace-symbol=__libc_init',f'-Wl,-Map={build}/scarletnx-ndk-fixed.map']
args.extend([f'-L{cxx}',f'-L{api}',f'-L{rt}','-lc++_shared','-lunwind','-ldl','-lm','-lc',f'{api}/crtend_so.o'])
pathlib.Path(build,'scarletnx-relink-fixed.sh').write_text('#!/bin/sh\nexec '+shlex.join(args)+'\n')
print('CORRECT_LINK_COMMAND_READY')
PY
BACKUP="$TARGET.before-fixed-relink"
cp -f "$TARGET" "$BACKUP"
restore() { cp -f "$BACKUP" "$TARGET"; }
trap restore EXIT
{
 echo SCARLETNX_RELINK_CORRIGIDO
 echo '=== LINK ==='
 set +e
 (cd "$BUILD" && sh scarletnx-relink-fixed.sh)
 STATUS=$?
 set -e
 echo "LINK_EXIT=$STATUS"
 if [[ "$STATUS" == 0 ]]; then
   echo '=== NEEDED ==='
   readelf -d "$TARGET" | grep NEEDED || true
   echo '=== DEFINITIONS ==='
   readelf -Ws "$TARGET" | grep -E ' (getauxval|__libc_init)$' | head -12 || true
   if readelf -d "$TARGET" | grep -q 'NEEDED.*libc[.]so' && ! readelf -Ws "$TARGET" | grep -E ' (getauxval|__libc_init)$' | grep -q ' FUNC .* GLOBAL DEFAULT '; then
     echo 'RELINK_FIXED_ELF_VALIDATED (original restored; APK not built)'
   else
     echo 'RELINK_FIXED_ELF_NOT_VALIDATED'
   fi
 fi
 echo '=== LINK MAP ==='
 if [[ -s "$BUILD/scarletnx-ndk-fixed.map" ]]; then
  grep -n -B 3 -A 3 -E 'getauxval|__libc_init' "$BUILD/scarletnx-ndk-fixed.map" | head -70 || true
 else echo MAP_NOT_CREATED; fi
 echo 'ORIGINAL_RESTORED_ON_EXIT'
} > "$REPORT" 2>&1
echo "RELATORIO_GERADO=$REPORT"
