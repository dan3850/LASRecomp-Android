#!/data/data/com.termux/files/usr/bin/bash
# Experimental relink of existing ScarletNX GUI library. Does not rebuild LLVM or APK.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
BUILD="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
NDK="${ANDROID_NDK_ROOT:-$HOME/android-sdk/ndk/28.2.13676358}"
SYS="$NDK/toolchains/llvm/prebuilt/sysroot"
API="$SYS/usr/lib/aarch64-linux-android/24"
CXX="$SYS/usr/lib/aarch64-linux-android"
RUNTIME="$NDK/toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33"
TARGET="$BUILD/src/gui/libmain.so"
DEST="$HOME/storage/downloads/ScarletNX-relink-ndk.txt"
mkdir -p "$(dirname "$DEST")"
for f in "$API/crtbegin_so.o" "$API/crtend_so.o" "$API/libc.so" "$CXX/libc++_shared.so" "$RUNTIME/libunwind.a"; do
 [[ -s "$f" ]] || { echo "Arquivo necessario ausente: $f"; exit 2; }
done
[[ -s "$TARGET" && -f "$BUILD/build.ninja" ]] || { echo "Build existente ausente"; exit 2; }
# Find the complete existing link command, and modify only its driver defaults.
python3 - "$BUILD" "$API" "$CXX" "$RUNTIME" <<'PY'
import subprocess,sys,shlex,pathlib
build,api,cxx,rt=sys.argv[1:]
lines=subprocess.check_output(['ninja','-C',build,'-t','commands'],text=True).splitlines()
matches=[x for x in lines if '-o src/gui/libmain.so ' in x]
if len(matches)!=1:
    raise SystemExit(f'ERRO: esperado 1 comando de link; encontrados {len(matches)}')
line=matches[0]
# Existing Ninja command is ": && clang++ ... && :". Keep its original libraries.
parts=shlex.split(line)
try:
    i=parts.index('-o')
    assert parts[i+1]=='src/gui/libmain.so'
except (ValueError,IndexError,AssertionError):
    raise SystemExit('ERRO: formato do comando de link inesperado')
# Insert flags before objects, preserve existing library ordering, add NDK runtimes last.
# -nostdlib disables implicit Termux CRT, libc, C++ and compiler-rt.
compiler=next((i for i,x in enumerate(parts) if x.endswith('/clang++')),None)
if compiler is None: raise SystemExit('ERRO: clang++ nao encontrado')
parts[compiler+1:compiler+1]=['-nostdlib','-Wl,--no-undefined']
parts[i+3:i+3]=[]  # no-op; retain original order
end=next((j for j in range(len(parts)-1,0,-1) if parts[j]=='&&'),None)
if end is None: raise SystemExit('ERRO: comando Ninja sem terminador')
extra=[f'{api}/crtbegin_so.o',f'-L{cxx}',f'-L{rt}', '-lc++_shared','-lunwind','-ldl','-lm','-lc',f'{api}/crtend_so.o']
# crtbegin must precede application objects; crtend must be at the end.
parts.insert(compiler+2,f'{api}/crtbegin_so.o')
end=next(j for j in range(len(parts)-1,0,-1) if parts[j]=='&&')
parts[end:end]=extra[1:-1]+[extra[-1]]
cmd=shlex.join(parts)
pathlib.Path(build,'scarletnx-ndk-relink-command.sh').write_text('#!/bin/sh\n'+cmd+'\n')
print('RELINK_COMMAND_READY')
PY
BACKUP="$TARGET.before-ndk-relink"
cp -f "$TARGET" "$BACKUP"
{
echo "SCARLETNX_NDK_RELINK"
echo "ORIGINAL_SHA=$(sha256sum "$BACKUP")"
if (cd "$BUILD" && bash scarletnx-ndk-relink-command.sh); then
 echo "=== NEW NEEDED ==="
 readelf -d "$TARGET" | grep NEEDED || true
 echo "=== GETAUXVAL / LIBC INIT ==="
 readelf -Ws "$TARGET" | grep -E ' getauxval$| __libc_init$' || true
 if readelf -d "$TARGET" | grep -q 'NEEDED.*libc[.]so' && ! readelf -Ws "$TARGET" | grep -Eq '[[:space:]](getauxval|__libc_init)$'; then
  echo "RELINK_NDK_VALIDATED"
 else
  echo "RELINK_INVALID_RESTORING"
  cp -f "$BACKUP" "$TARGET"
 fi
else
 echo "RELINK_FAILED_RESTORING"
 cp -f "$BACKUP" "$TARGET"
fi
} > "$DEST" 2>&1
echo "RELATORIO_GERADO=$DEST"
