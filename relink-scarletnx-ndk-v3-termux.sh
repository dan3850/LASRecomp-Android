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
REPORT="$HOME/storage/downloads/ScarletNX-relink-ndk-v3.txt"
mkdir -p "$(dirname "$REPORT")"
[[ -s "$TARGET" && -s "$BUILD/build.ninja" ]] || { echo "ERRO: build nativa nao encontrada"; exit 2; }
for f in "$API/crtbegin_so.o" "$API/crtend_so.o" "$API/libc.so" "$API/libm.so" "$CXX/libc++_shared.so"; do [[ -s "$f" ]] || { echo "ERRO: arquivo NDK ausente $f"; exit 2; }; done
python3 - "$BUILD" "$API" "$CXX" "$RT" <<'PY'
import pathlib,sys,subprocess,shlex
build,api,cxx,rt=sys.argv[1:]
r=subprocess.run(['ninja','-C',build,'-t','commands','src/gui/libmain.so'],capture_output=True,text=True)
if r.returncode: raise SystemExit(r.stderr)
lines=[x for x in r.stdout.splitlines() if ' -o src/gui/libmain.so ' in x and 'clang++' in x]
if len(lines)!=1: raise SystemExit(f'Expected one linker command, found {len(lines)}')
line=lines[0].strip()
if not(line.startswith(': && ') and line.endswith(' && :')): raise SystemExit('Unexpected Ninja command wrapper')
args=shlex.split(line[5:-5])
if not args[0].endswith('clang++'): raise SystemExit('Unexpected linker driver')
# Disable all implicit host libraries. Force exact NDK API-24 dynamic stubs,
# never generic libc.a/libm.a from the sysroot parent directory.
args[1:1]=['-nostdlib',f'{api}/crtbegin_so.o','-Wl,--trace-symbol=getauxval','-Wl,--trace-symbol=__libc_init']
# Strip host-dependent search paths and implicit -lm/-ldl from original command.
args=[x for x in args if x not in ('-lm','-ldl','-latomic','-pthread','-mabi=elfv2')]
runtime=pathlib.Path(rt)/'libclang_rt.builtins-aarch64-android.a'
if not runtime.is_file(): raise SystemExit(f'Missing compiler runtime: {runtime}')
unwind=pathlib.Path(rt)/'libunwind.a'
# The C++ runtime is dynamic; ensure explicit API 24 shared libc/libm.
args += [str(pathlib.Path(cxx)/'libc++_shared.so'),str(pathlib.Path(api)/'libm.so'),str(pathlib.Path(api)/'libdl.so') if (pathlib.Path(api)/'libdl.so').is_file() else '-ldl',str(pathlib.Path(api)/'libc.so'),str(runtime)]
if unwind.is_file(): args.append(str(unwind))
args += [str(pathlib.Path(api)/'libc.so'),str(pathlib.Path(api)/'crtend_so.o')]
pathlib.Path(build,'scarletnx-relink-v3.sh').write_text('#!/bin/sh\nexec '+shlex.join(args)+'\n')
print('LINK_COMMAND_V3_READY')
PY
BACKUP="$TARGET.before-ndk-v3"
cp -f "$TARGET" "$BACKUP"
restore() { cp -f "$BACKUP" "$TARGET"; }
trap restore EXIT
{
echo SCARLETNX_NDK_RELINK_V3
echo '=== LINK ==='
set +e
(cd "$BUILD" && sh scarletnx-relink-v3.sh)
STATUS=$?
set -e
echo "LINK_EXIT=$STATUS"
if [[ "$STATUS" == 0 ]]; then
 echo '=== DYNAMIC DEPENDENCIES ==='
 readelf -d "$TARGET" | grep NEEDED || true
 echo '=== DEFINITIONS ==='
 readelf -Ws "$TARGET" | grep -E ' (getauxval|__libc_init)$' | head -15 || true
 if readelf -d "$TARGET" | grep -q 'NEEDED.*libc[.]so' && ! readelf -Ws "$TARGET" | awk '$7 != "UND" && ($8=="getauxval" || $8=="__libc_init") {found=1} END{exit !found}'; then
   echo 'RELINK_V3_VALIDATED'
 else
   echo 'RELINK_V3_INVALID'
 fi
fi
echo ORIGINAL_RESTORED_ON_EXIT
} > "$REPORT" 2>&1
echo "RELATORIO_GERADO=$REPORT"
