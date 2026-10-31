#!/data/data/com.termux/files/usr/bin/bash
set -uo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
BUILD="$ROOT/scarletnx-android-apk-2026/arm64-v8a"
TARGET="$BUILD/src/gui/libmain.so"
REPORT="$HOME/storage/downloads/ScarletNX-origem-libc-v2.txt"
mkdir -p "$(dirname "$REPORT")"
exec > >(tee "$REPORT") 2>&1
echo SCARLETNX_ORIGEM_LIBC_V2
echo "DATE=$(date)"
echo "TARGET=$TARGET"
for x in clang++ ld.lld llvm-nm nm readelf ninja; do command -v "$x" || true; done
if [[ ! -f "$TARGET" ]]; then echo TARGET_MISSING; exit 2; fi
echo '=== SYMBOLS IN CURRENT LIBMAIN ==='
readelf -Ws "$TARGET" | grep -E ' (getauxval|__libc_init)$' | head -12 || true
echo '=== EXISTING LINK COMMAND ==='
if [[ -f "$BUILD/scarletnx-ndk-relink-command.sh" ]]; then
  head -c 1500 "$BUILD/scarletnx-ndk-relink-command.sh"; echo
else
  echo RELINK_COMMAND_MISSING
fi
echo '=== NINJA TARGET COMMAND ==='
if [[ -f "$BUILD/build.ninja" ]]; then
 ninja -C "$BUILD" -t commands src/gui/libmain.so 2>&1 | tail -c 3500 || true
fi
echo '=== ARCHIVES WITH SYMBOLS (INCLUDING ROOT CACHE) ==='
python3 - "$BUILD" "$ROOT/android-llvm" <<'PY'
import pathlib,subprocess,sys,concurrent.futures
roots=[pathlib.Path(x) for x in sys.argv[1:]]
files=[]
for root in roots:
 if root.exists():
  files.extend(p for p in root.rglob('*') if p.suffix in ('.a','.o') and p.is_file())
print('FILES_TO_SCAN',len(files),flush=True)
nm=subprocess.run(['sh','-c','command -v llvm-nm || command -v nm'],capture_output=True,text=True).stdout.strip()
print('NM',nm,flush=True)
if not nm: sys.exit(0)
def scan(p):
 try:
  r=subprocess.run([nm,'-A','--defined-only',str(p)],capture_output=True,text=True,timeout=12)
  hits=[x for x in r.stdout.splitlines() if x.rstrip().endswith((' getauxval',' __libc_init',' __libc_init_main_thread_early',' __libc_init_main_thread_late'))]
  return hits[:6]
 except Exception: return []
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 for hits in ex.map(scan,files):
  for line in hits: print(line,flush=True)
PY
echo '=== ELF SECTIONS ==='
readelf -S "$TARGET" | grep -E 'symtab|dynsym|debug|comment' || true
echo ORIGIN_V2_COMPLETE
