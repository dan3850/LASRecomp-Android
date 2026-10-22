#!/data/data/com.termux/files/usr/bin/bash
# Build the pinned ScarletNX Android arm64 runtime with external RomFS graft.
# Does not rebuild the 107 MB Mario AOT module or discard existing build caches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
die() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }
test "$(uname -m)" = aarch64 || die "Execute em Termux ARM64"
for tool in git python3 cmake ninja clang llvm-nm llvm-readelf llvm-objdump; do
  command -v "$tool" >/dev/null || die "Ferramenta ausente: $tool (pkg install git python cmake ninja clang)"
done

BASE="$HOME/.cache/lasrecomp-scarletnx-romfs"
SRC="$BASE/ScarletNX"
BUILD="$BASE/android-arm64-build"
AUDIT="$BASE/elf-audit/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$AUDIT"
exec > >(tee -a "$AUDIT/build.log") 2>&1
echo "SCARLETNX_LINK_EVIDENCE: $AUDIT"
# Termux already packages usable ARM64 LLVM libraries and their CMake config.
# Do not cross-build another LLVM using the NDK compiler wrapper.
LLVM_PREFIX="${SCARLETNX_LLVM_PREFIX:-$PREFIX}"
OUT="${SCARLETNX_RUNTIME_OUT:-$HOME/scarletnx-romfs-build/libscarletnx.so}"
COMMIT=34853eeae5af132e320adbb0193f13344085bf89
# Android may kill Termux when independent ExternalProject jobs fan out.
# Propagate a conservative limit to OpenSSL, FFmpeg and Ninja alike.
JOBS="${SCARLETNX_BUILD_JOBS:-2}"
export CMAKE_BUILD_PARALLEL_LEVEL="$JOBS"
export MAKEFLAGS="-j$JOBS"
echo "TERMUX_BUILD_PARALLELISM: $JOBS (including OpenSSL and FFmpeg)"

# The current NDK is already used by the project's existing Termux builds.
if [ -z "${ANDROID_NDK_ROOT:-}" ]; then
  for candidate in "${ANDROID_HOME:-$HOME/Android/Sdk}"/ndk/* "$HOME/android-sdk/ndk/"*; do
    if [ -f "$candidate/build/cmake/android.toolchain.cmake" ]; then
      ANDROID_NDK_ROOT="$candidate"
    fi
  done
fi
export ANDROID_NDK_ROOT="${ANDROID_NDK_ROOT:-}"
[ -f "$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" ] ||
  die "NDK nao encontrado. Defina ANDROID_NDK_ROOT apontando para NDK r28c."
export ANDROID_NDK_HOME="$ANDROID_NDK_ROOT"
NDK_SYSROOT="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot"
NDK_API_LIB="$NDK_SYSROOT/usr/lib/aarch64-linux-android/26"
[ -s "$NDK_API_LIB/libc.so" ] ||
  die "Import library Android26 ausente: $NDK_API_LIB/libc.so. Nao usaremos libc.a como fallback."
mkdir -p "$BASE" "$(dirname "$OUT")"

# Record the old ELF BEFORE modifying sources/relinking. A previous export-only
# fix can hide getauxval from .dynsym while its LOCAL definition still crashes.
OLD_RUNTIME="$BUILD/libscarletnx.so"
[ -s "$OLD_RUNTIME" ] || OLD_RUNTIME="$BUILD/src/nx/libscarletnx.so"
if [ -s "$OLD_RUNTIME" ]; then
  python3 "$ROOT/tools/scarletnx_elf_audit.py" "$OLD_RUNTIME" \
    --report-only --output "$AUDIT/before.json" \
    --archive "$NDK_API_LIB/libc.a" \
    --archive "$NDK_SYSROOT/usr/lib/aarch64-linux-android/libc.a" \
    --archive "$PREFIX/lib/libatomic.a" --archive "$PREFIX/lib/libunwind.a"
fi
if [ -s "$BUILD/build.ninja" ]; then
  ninja -C "$BUILD" -t commands scarletnx > "$AUDIT/before-ninja-commands.txt"
  if [ -s "$AUDIT/before.json" ] && python3 - "$AUDIT/before.json" <<'PY'
import json
import sys
from pathlib import Path
raise SystemExit(0 if json.loads(Path(sys.argv[1]).read_text())['platform_definitions'] else 1)
PY
  then
    # One diagnostic relink is necessary to prove WHICH archive supplied the
    # already-linked private libc. It compiles no source and cannot replace the
    # installed/output DSO. If old objects are unavailable, record that limit.
    python3 "$ROOT/tools/scarletnx_link_probe.py" --build "$BUILD" \
      --output "$AUDIT/before-relink" ||
      echo "AVISO: origem antiga indisponivel; consulte before.json e before-relink. O ELF corrigido ainda precisa passar."
  fi
fi

if [ ! -d "$SRC/.git" ]; then
  echo "Obtendo codigo ScarletNX original..."
  git clone --filter=blob:none https://github.com/scarletnx/ScarletNX.git "$SRC"
fi
cd "$SRC"
if [ "$(git rev-parse HEAD)" != "$COMMIT" ]; then
  [ -z "$(git status --porcelain)" ] || die "Fonte ScarletNX modificada no cache: $SRC"
  git fetch --depth 1 origin "$COMMIT"
  git checkout --detach "$COMMIT"
fi

python3 "$ROOT/tools/patch_scarletnx_romfs.py" "$SRC"
if [ "${SCARLETNX_CASTLEVANIA_FSWZADD:-0}" = 1 ]; then
  echo "FSWZADD: applying limited 0xD7 experiment to Castlevania runtime source"
  python3 "$ROOT/tools/patch_scarletnx_fswzadd.py" "$SRC"
else
  # Do not accidentally ship the Castlevania shader experiment in a later
  # standard Mario runtime build that reuses this local ScarletNX checkout.
  python3 "$ROOT/tools/patch_scarletnx_fswzadd.py" "$SRC" --revert
fi
# Termux's LLVM21 ships llvm-config plus shared LLVM, while its CMake
# LLVMExports may name static .a components not installed on the phone.
# Native Termux builds can query llvm-config; cross builds cannot.
LLVM_CMAKE="$SRC/cmake/llvm.cmake"
python3 - "$LLVM_CMAKE" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'if(ANDROID OR IOS OR (APPLE AND LLVM_DIR AND NOT SNX_LLVM_CONFIG))'
new = 'if((ANDROID AND NOT SNX_TERMUX_NATIVE_LLVM) OR IOS OR (APPLE AND LLVM_DIR AND NOT SNX_LLVM_CONFIG))'
if s.count(new) == 1:
    print("LLVM Termux CMake integration already applied")
elif s.count(old) == 1:
    s = s.replace(old, new)
    print("LLVM Termux CMake integration applied")
else:
    raise SystemExit("Unknown ScarletNX LLVM configuration; refusing automatic patch")
# Only the Termux path uses shared LLVM, so the standard desktop builds
# retain their existing component-linking semantics.
a = 'snx_llvm_query(SNX_LLVM_LIBS --libs ${SNX_LLVM_COMPONENTS})'
b = '''if(SNX_TERMUX_NATIVE_LLVM)
    snx_llvm_query(SNX_LLVM_LIBS --link-shared --libs ${SNX_LLVM_COMPONENTS})
else()
    snx_llvm_query(SNX_LLVM_LIBS --libs ${SNX_LLVM_COMPONENTS})
endif()'''
# Older versions nested this replacement on every invocation because `a` is
# also present in b's else branch. Collapse those exact generated blocks first.
while b in s:
    s = s.replace(b, a, 1)
if s.count(a) == 1:
    s = s.replace(a, b, 1)
else:
    raise SystemExit("LLVM component query changed; refusing patch")
a = 'snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)'
b = '''if(SNX_TERMUX_NATIVE_LLVM)
        snx_llvm_query(SNX_LLVM_DISASM_LIBS --link-shared --libs aarch64disassembler aarch64desc aarch64info)
    else()
        snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)
    endif()'''
while b in s:
    s = s.replace(b, a, 1)
if s.count(a) == 1:
    s = s.replace(a, b, 1)
else:
    raise SystemExit("LLVM disassembler query changed; refusing patch")
if p.read_text() != s:
    p.write_text(s)
PY

[ -f "$LLVM_PREFIX/lib/cmake/llvm/LLVMConfig.cmake" ] ||
  die "LLVMConfig.cmake ausente em $LLVM_PREFIX; instale pkg install llvm"
# FFmpeg runs its own configure/link probes outside CMake, so it does
# not inherit CMAKE_EXE_LINKER_FLAGS. Provide Termux's ARM64 libunwind
# and atomic paths explicitly to FFmpeg only. Keep the upstream NDK
# target/sysroot and the existing source/cache unchanged.
FFMPEG_CMAKE="$SRC/cmake/ffmpeg.cmake"
python3 - "$FFMPEG_CMAKE" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
needle = 'if(ANDROID)\n    # the NDK\'s Clang takes its target and sysroot as flags'
replacement = '''if(ANDROID)
    # Termux-hosted NDK wrapper: FFmpeg configure links probes itself,
    # outside CMake's linker flags. The native ARM64 unwind archive is
    # available in the Termux prefix, not the wrapper's sysroot.
    if(SNX_TERMUX_NATIVE_LLVM)
        list(APPEND snx_ffmpeg_args "--extra-ldflags=-L$ENV{PREFIX}/lib")
    endif()
    # the NDK's Clang takes its target and sysroot as flags'''
if s.count(replacement) == 1:
    print("Termux FFmpeg linker patch already applied")
elif s.count(needle) == 1:
    p.write_text(s.replace(needle, replacement, 1))
    print("Patched FFmpeg configure linker flags for Termux")
else:
    raise SystemExit("Unexpected FFmpeg source structure; refusing patch")
PY

# OpenSSL's Android Configure chooses <triple><API>-clang by name,
# unlike CMake/FFmpeg, which use the NDK clang wrapper directly.
# Native Termux installations of the NDK expose only clang. Provide
# precisely the expected alias in a private PATH, forwarding to the same
# verified ARM64 compiler with its target/sysroot and Termux unwind path.
OPENSSL_CC_BIN="$BASE/openssl-cc-bin"
mkdir -p "$OPENSSL_CC_BIN"
printf '#!/data/data/com.termux/files/usr/bin/sh\nexec "%s" --target=aarch64-none-linux-android26 --sysroot="%s" -L"%s" "$@"\n' \
  "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/bin/clang" \
  "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot" "$PREFIX/lib" \
  > "$OPENSSL_CC_BIN/aarch64-linux-android26-clang"
chmod 755 "$OPENSSL_CC_BIN/aarch64-linux-android26-clang"
export SNX_TERMUX_OPENSSL_BIN="$OPENSSL_CC_BIN"
echo "OPENSSL_CC_READY: $OPENSSL_CC_BIN/aarch64-linux-android26-clang"
OPENSSL_CMAKE="$SRC/cmake/openssl.cmake"
python3 - "$OPENSSL_CMAKE" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = '"PATH=${ANDROID_TOOLCHAIN_ROOT}/bin:$ENV{PATH}"'
new = '"PATH=$ENV{SNX_TERMUX_OPENSSL_BIN}:${ANDROID_TOOLCHAIN_ROOT}/bin:$ENV{PATH}"'
if s.count(new) == 1:
    print("OpenSSL Termux compiler PATH patch already applied")
elif s.count(old) == 1:
    s = s.replace(old, new, 1)
    p.write_text(s)
    print("Patched OpenSSL Android compiler PATH")
else:
    raise SystemExit("Unexpected OpenSSL CMake source; refusing patch")
PY

LLVM_CONFIG="$LLVM_PREFIX/bin/llvm-config"
[ -x "$LLVM_CONFIG" ] || die "llvm-config do Termux nao encontrado em $LLVM_CONFIG"
if ! LLVM_LIBS="$("$LLVM_CONFIG" --link-shared --libs core orcjit native 2>&1)"; then
  die "llvm-config nao conseguiu descrever bibliotecas LLVM compartilhadas: $LLVM_LIBS"
fi
echo "LLVM_SHARED_LIBS: $LLVM_LIBS"
# Validate that llvm-config emits a shared-library linker name rather
# than a list of absent static component archives.
if ! printf '%s' "$LLVM_LIBS" | grep -E -- '-lLLVM([ -]|$)' >/dev/null; then
  echo "AVISO: LLVM compartilhado nao aparece na consulta; CMake validara os componentes."
fi
[ -f "$PREFIX/lib/libatomic.a" ] || die "Termux libatomic.a ausente"
[ -f "$PREFIX/lib/libunwind.a" ] || die "Termux libunwind.a ausente"
echo "Reutilizando LLVM ARM64 do Termux: $LLVM_PREFIX"
# NDK clang wrapper uses the NDK sysroot. The Termux native ARM64
# atomic/unwind archives are compatible in architecture, but are outside
# that sysroot's default library search path. Supply an explicit -L.
# No host-only x86_64 NDK executable is invoked.
# Shared Termux LLVM must use its matching C++ provider. Use this same exact
# file for linking and the private SNX SONAME in the APK; no original-APK C++
# or later LASRecomp staging override may silently replace it.
CXX_RUNTIME="$PREFIX/lib/libc++_shared.so"
[ -s "$CXX_RUNTIME" ] || die "libc++_shared.so do LLVM Termux ausente: $CXX_RUNTIME"
echo "C++ runtime: $CXX_RUNTIME"
# Do not add the general NDK C++ directory to -L just to find one .so: it
# also contains platform static libraries on some NDK layouts. The API import
# directory comes first, and the C++ .so is already named by its exact path.
LINK_FLAGS="-L$NDK_API_LIB -L$PREFIX/lib"
# The NDK toolchain injects -static-libstdc++ when linking. Its implicit
# -lc++_shared resolution fails on the native Termux wrapper even with -L.
# Tell Clang not to add a second implicit C++ runtime and link the exact
# already-validated ARM64 .so file via the CMake standard libraries slot.
# This setting also applies to CMake's CXX try_compile() before configure.
CXX_FLAGS="-nostdlib++"

# Fail early, with a short and reproducible diagnostic, if the NDK wrapper
# cannot use the explicit C++ runtime. Do not discard the CMake cache.
CHECK_DIR="$BASE/clang-cxx-probe"
mkdir -p "$CHECK_DIR"
# Unlike an empty main, this probe pulls the CPU-capability path into the ELF.
printf '#include <sys/auxv.h>\nint main() { return getauxval(AT_HWCAP) == 0; }\n' > "$CHECK_DIR/main.cpp"
NDK_CLANGXX="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/bin/clang++"
if ! "$NDK_CLANGXX" --target=aarch64-none-linux-android26 \
  --sysroot="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot" \
  -nostdlib++ "$CHECK_DIR/main.cpp" -o "$CHECK_DIR/main" \
  -L"$NDK_API_LIB" -L"$PREFIX/lib" "$CXX_RUNTIME" \
  -Wl,--push-state,--no-as-needed "$NDK_API_LIB/libc.so" -Wl,--pop-state \
  -latomic -lm; then
  die "Teste C++ isolado falhou; confira as bibliotecas ARM64 do NDK e Termux."
fi
python3 "$ROOT/tools/scarletnx_elf_audit.py" "$CHECK_DIR/main" \
  --output "$AUDIT/cxx-probe.json"
if ! LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$CHECK_DIR/main"; then
  die "Probe getauxval falhou no proprio Termux; veja $AUDIT/cxx-probe.json"
fi
echo "CXX_PROBE_OK: getauxval da libc Android vinculado e executado no Termux"


# Keep the public SDL/JNI API allowlist. This is export hygiene, NOT the libc
# fix: the audit below rejects local/hidden libc definitions as well.
SYMBOL_MAP="$BASE/scarletnx-android-symbols.map"
cat > "$SYMBOL_MAP.tmp" <<'MAP'
{
  global:
    main;
    JNI_OnLoad;
    Java_*;
    SDL_*;
  local: *;
};
MAP
if ! cmp -s "$SYMBOL_MAP.tmp" "$SYMBOL_MAP"; then
  mv -f "$SYMBOL_MAP.tmp" "$SYMBOL_MAP"
else
  rm -f "$SYMBOL_MAP.tmp"
fi
python3 "$ROOT/tools/patch_scarletnx_android_link.py" "$SRC" \
  --libc "$NDK_API_LIB/libc.so" --cxx "$CXX_RUNTIME" \
  --symbol-map "$SYMBOL_MAP" --evidence "$AUDIT"

echo "Configurando ScarletNX ARM64 com RomFS externa..."
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
  -DLLVM_DIR="$LLVM_PREFIX/lib/cmake/llvm" \
  -DSNX_TERMUX_NATIVE_LLVM=ON \
  -DSNX_LLVM_CONFIG="$LLVM_CONFIG" \
  -DCMAKE_EXE_LINKER_FLAGS="$LINK_FLAGS" \
  -DCMAKE_CXX_FLAGS="$CXX_FLAGS" \
  -DCMAKE_CXX_STANDARD_LIBRARIES="$CXX_RUNTIME" \
  -DCMAKE_SHARED_LINKER_FLAGS="$LINK_FLAGS" \
  -DCMAKE_MODULE_LINKER_FLAGS="$LINK_FLAGS" \
  -DSNX_DEPLOY=OFF -DSNX_BUILD_GNUABI=OFF -DSNX_BUILD_3DS=OFF \
  -DSNX_BUILD_GUI=OFF -DBUILD_TESTING=OFF \
  -DCMAKE_BUILD_TYPE=Release

echo "Compilando somente a biblioteca ScarletNX (mantendo o cache)..."
cmake --build "$BUILD" --target scarletnx --parallel "$JOBS" --verbose \
  2>&1 | tee "$AUDIT/link.log"
RUNTIME="$BUILD/libscarletnx.so"
[ -s "$RUNTIME" ] || RUNTIME="$(find "$BUILD" -name libscarletnx.so -type f -print -quit)"
[ -s "$RUNTIME" ] || die "Compilacao terminou mas libscarletnx.so nao encontrada"

# Trace/map/why-extract name the actual archive members (including the compiler
# runtime's LSE initializer). The binary policy must pass before OUT or APK changes.
BUILTINS="$("$NDK_CLANGXX" --target=aarch64-none-linux-android26 \
  --sysroot="$NDK_SYSROOT" --print-libgcc-file-name)"
python3 "$ROOT/tools/scarletnx_elf_audit.py" "$RUNTIME" \
  --output "$AUDIT/after.json" --require-main --require-trace \
  --link-log "$AUDIT/link.log" --link-map "$AUDIT/scarletnx.map" \
  --why-extract "$AUDIT/why-extract.tsv" \
  --archive "$BUILTINS" --archive "$NDK_API_LIB/libc.a" \
  --archive "$NDK_SYSROOT/usr/lib/aarch64-linux-android/libc.a" \
  --archive "$PREFIX/lib/libatomic.a" --archive "$PREFIX/lib/libunwind.a"
printf '%s\n' "$CXX_RUNTIME" > "$BASE/selected-cxx-runtime.path"
printf '%s\n' "$AUDIT" > "$BASE/latest-elf-audit.path"

# Inspect the dynamic exports and prevent libc symbol interposition.
SYMBOL_EXPORTS="$BASE/scarletnx-dynamic-exports.txt"
llvm-nm -D --defined-only "$RUNTIME" > "$SYMBOL_EXPORTS" ||
  die "Falha ao inspecionar as exportacoes ELF do ScarletNX"
for required in main JNI_OnLoad; do
  grep -E "[[:space:]]${required}$" "$SYMBOL_EXPORTS" >/dev/null ||
    die "Entrada publica obrigatoria do ScarletNX ausente: $required"
done
if grep -E '[[:space:]](getauxval|strcmp|newlocale|memset|memcpy|memmove)$' "$SYMBOL_EXPORTS" >/dev/null; then
  grep -E '[[:space:]](getauxval|strcmp|newlocale|memset|memcpy|memmove)$' "$SYMBOL_EXPORTS" >&2
  die "Simbolos libc ainda exportados pelo ScarletNX; interrompendo APK"
fi
echo "SCARLETNX_LIBC_INTERPOSITION_GUARD: OK"
echo "SCARLETNX_EXPORT_ALLOWLIST: OK"

grep -aF 'SNX_EXTERNAL_ROMFS' "$RUNTIME" >/dev/null ||
  die "Build sem suporte ao graft. Bibliotecas originais nao serao substituidas."

cp "$RUNTIME" "$OUT"
python3 - "$AUDIT/selected-runtime-libraries.json" "$AUDIT/after.json" "$OUT.link.json" <<'PY'
import json
import sys
from pathlib import Path
metadata = json.loads(Path(sys.argv[1]).read_text())
metadata['runtime_sha256'] = json.loads(Path(sys.argv[2]).read_text())['sha256']
Path(sys.argv[3]).write_text(json.dumps(metadata, indent=2) + '\n')
PY
echo "===== SCARLETNX MODIFICADO PRONTO ====="
ls -lh "$OUT"
echo "===== COMPILANDO APK MARIO ====="
cd "$ROOT"
export SCARLETNX_PATCHED_RUNTIME_SO="$OUT"
bash compilar-mario-snx-runtime-termux.sh
