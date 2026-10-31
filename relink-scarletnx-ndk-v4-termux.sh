#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
BUILD="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
NDK="$HOME/android-sdk/ndk/28.2.13676358"
SYS="$NDK/toolchains/llvm/prebuilt/sysroot"
API="$SYS/usr/lib/aarch64-linux-android/24"
CXX="$SYS/usr/lib/aarch64-linux-android"
RT="$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/19/lib/linux/libclang_rt.builtins-aarch64-android.a"
TARGET="$BUILD/src/gui/libmain.so"
REPORT="$HOME/storage/downloads/ScarletNX-relink-ndk-v4.txt"
mkdir -p "$(dirname "$REPORT")"
[[ -s "$TARGET" && -s "$BUILD/build.ninja" ]] || { echo "ERRO: build ausente"; exit 2; }
for f in "$API/crtbegin_so.o" "$API/crtend_so.o" "$API/libc.so" "$API/libm.so" "$CXX/libc++_shared.so" "$RT"; do [[ -s "$f" ]] || { echo "ERRO: arquivo ausente $f"; exit 2; }; done
python3 - "$BUILD" "$API" "$CXX" "$RT" <<'PY'
import pathlib,sys,subprocess,shlex
build,api,cxx,rt=sys.argv[1:]
r=subprocess.run(['ninja','-C',build,'-t','commands','src/gui/libmain.so'],capture_output=True,text=True,check=True)
lines=[x for x in r.stdout.splitlines() if ' -o src/gui/libmain.so ' in x and 'clang++' in x]
if len(lines)!=1: raise SystemExit('Expected exactly one linker command')
line=lines[0].strip()
if not(line.startswith(': && ') and line.endswith(' && :')): raise SystemExit('Unexpected command wrapper')
args=shlex.split(line[5:-5])
if not args[0].endswith('clang++'): raise SystemExit('Unexpected linker')
args=[x for x in args if x not in ('-lm','-ldl','-latomic','-pthread','-mabi=elfv2')]
args[1:1]=['-nostdlib',f'{api}/crtbegin_so.o','-Wl,--trace-symbol=getauxval','-Wl,--trace-symbol=__libc_init']
# Absolute shared-library stubs prevent the parent sysroot libc.a from being chosen.
args += [f'{cxx}/libc++_shared.so',f'{api}/libm.so',f'{api}/libdl.so',f'{api}/libc.so',rt,f'{api}/libc.so',f'{api}/crtend_so.o']
pathlib.Path(build,'scarletnx-relink-v4.sh').write_text('#!/bin/sh\nexec '+shlex.join(args)+'\n')
PY
BACKUP="$TARGET.before-ndk-v4"
cp -f "$TARGET" "$BACKUP"
trap 'cp -f "$BACKUP" "$TARGET"' EXIT
{
echo SCARLETNX_RELINK_NDK_V4
echo "COMPILER_RUNTIME=$RT"
set +e
(cd "$BUILD" && sh scarletnx-relink-v4.sh)
status=$?
set -e
echo "LINK_EXIT=$status"
if [[ "$status" == 0 ]]; then
 echo '=== NEEDED ==='
 readelf -d "$TARGET" | grep NEEDED || true
 echo '=== SYMBOLS ==='
 readelf -Ws "$TARGET" | grep -E ' (getauxval|__libc_init)$' | head -12 || true
 if readelf -d "$TARGET" | grep -q 'NEEDED.*libc[.]so' && ! readelf -Ws "$TARGET" | awk '$7 != "UND" && ($8=="getauxval" || $8=="__libc_init") {found=1} END{exit !found}'; then
 echo RELINK_V4_VALIDATED
 else echo RELINK_V4_INVALID; fi
fi
echo ORIGINAL_RESTORED_ON_EXIT
} > "$REPORT" 2>&1
echo "RELATORIO_GERADO=$REPORT"
