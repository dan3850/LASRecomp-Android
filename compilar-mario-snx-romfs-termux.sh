#!/data/data/com.termux/files/usr/bin/bash
# Build the pinned ScarletNX Android arm64 runtime with external RomFS graft.
# Does not rebuild the 107 MB Mario AOT module or discard existing build caches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
die() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }
test "$(uname -m)" = aarch64 || die "Execute em Termux ARM64"
for tool in git python3 cmake ninja clang; do
  command -v "$tool" >/dev/null || die "Ferramenta ausente: $tool (pkg install git python cmake ninja clang)"
done

BASE="$HOME/.cache/lasrecomp-scarletnx-romfs"
SRC="$BASE/ScarletNX"
BUILD="$BASE/android-arm64-build"
# Termux already packages usable ARM64 LLVM libraries and their CMake config.
# Do not cross-build another LLVM using the NDK compiler wrapper.
LLVM_PREFIX="${SCARLETNX_LLVM_PREFIX:-$PREFIX}"
OUT="$HOME/scarletnx-romfs-build/libscarletnx.so"
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
mkdir -p "$BASE" "$(dirname "$OUT")"

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
if a in s:
    s = s.replace(a, b, 1)
elif b not in s:
    raise SystemExit("LLVM component query changed; refusing patch")
a = 'snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)'
b = '''if(SNX_TERMUX_NATIVE_LLVM)
        snx_llvm_query(SNX_LLVM_DISASM_LIBS --link-shared --libs aarch64disassembler aarch64desc aarch64info)
    else()
        snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)
    endif()'''
if a in s:
    s = s.replace(a, b, 1)
elif b not in s:
    raise SystemExit("LLVM disassembler query changed; refusing patch")
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
# Android NDK clang++ links -lc++_shared by default. Its wrapper on
# native Termux does not supply the NDK libc++ search directory, so both
# the C compiler test and the C++ compiler test need explicit -L paths.
# Prefer the ABI-matched NDK library over a Termux-only alternative.
NDK_CXX=""
for candidate in \
  "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" \
  "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" \
  "$PREFIX/lib/libc++_shared.so"; do
  if [ -s "$candidate" ]; then NDK_CXX="$candidate"; break; fi
done
[ -n "$NDK_CXX" ] || die "libc++_shared.so ausente. Confira o NDK/Termux; nao crie biblioteca vazia."
echo "C++ runtime: $NDK_CXX"
LINK_FLAGS="-L$(dirname "$NDK_CXX") -L$PREFIX/lib"
# The NDK toolchain injects -static-libstdc++ when linking. Its implicit
# -lc++_shared resolution fails on the native Termux wrapper even with -L.
# Tell Clang not to add a second implicit C++ runtime and link the exact
# already-validated ARM64 .so file via the CMake standard libraries slot.
# This setting also applies to CMake's CXX try_compile() before configure.
CXX_FLAGS="-nostdlib++"
CXX_RUNTIME="$NDK_CXX"

# Fail early, with a short and reproducible diagnostic, if the NDK wrapper
# cannot use the explicit C++ runtime. Do not discard the CMake cache.
CHECK_DIR="$BASE/clang-cxx-probe"
mkdir -p "$CHECK_DIR"
printf 'int main() { return 0; }\n' > "$CHECK_DIR/main.cpp"
NDK_CLANGXX="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/bin/clang++"
if ! "$NDK_CLANGXX" --target=aarch64-none-linux-android26 \
  --sysroot="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot" \
  -nostdlib++ "$CHECK_DIR/main.cpp" -o "$CHECK_DIR/main" \
  $LINK_FLAGS "$CXX_RUNTIME" -latomic -lm; then
  die "Teste C++ isolado falhou; confira as bibliotecas ARM64 do NDK e Termux."
fi
echo "CXX_PROBE_OK: link nativo Android arm64 concluido"


# ScarletNX statically includes a getauxval() implementation that must
# remain callable internally, but exporting it can interpose libc's
# getauxval used by dynamically linked Termux libffi during constructors.
# Hide just that symbol in the shared runtime's .dynsym; keep all existing
# game/SDL entry points exported. Do not alter system libraries.
SYMBOL_MAP="$BASE/scarletnx-android-symbols.map"
cat > "$SYMBOL_MAP" <<'MAP'
{
  global: *;
  local: getauxval; memset; memcpy; memmove;
};
MAP
# Force only the runtime entry object/relink when the version script
# contents change; Ninja cannot always track external linker scripts.
# The heavyweight dependencies remain fully cached.
touch "$SRC/src/nx/runtime/entry.c"
SNX_CMAKE="$SRC/src/nx/CMakeLists.txt"
python3 - "$SNX_CMAKE" "$SYMBOL_MAP" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
script = Path(sys.argv[2])
s = p.read_text()
old = '    target_link_options(scarletnx PRIVATE -Wl,-Bsymbolic)'
new = old + '\\n    target_link_options(scarletnx PRIVATE "-Wl,--version-script=' + str(script) + '")'
new = new.replace('\\n', '\n')
if new in s:
    print("ScarletNX getauxval symbol visibility patch already applied")
elif s.count(old) == 1:
    p.write_text(s.replace(old, new, 1))
    print("ScarletNX getauxval export isolation enabled")
else:
    raise SystemExit("ScarletNX Android link options changed; refusing blind patch")
PY

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
cmake --build "$BUILD" --target scarletnx --parallel "$JOBS"
RUNTIME="$BUILD/src/nx/libscarletnx.so"
[ -s "$RUNTIME" ] || RUNTIME="$(find "$BUILD" -name libscarletnx.so -type f -print -quit)"
[ -s "$RUNTIME" ] || die "Compilacao terminou mas libscarletnx.so nao encontrada"

# Ensure the Android libc implementations cannot be interposed by our runtime.
if llvm-nm -D --defined-only "$RUNTIME" | grep -E '[[:space:]](getauxval|memset|memcpy|memmove)$' >/dev/null; then
  die "Simbolos libc ainda exportados pelo ScarletNX; interrompendo APK"
fi
echo "SCARLETNX_LIBC_INTERPOSITION_GUARD: OK"

grep -aF 'SNX_EXTERNAL_ROMFS' "$RUNTIME" >/dev/null ||
  die "Build sem suporte ao graft. Bibliotecas originais nao serao substituidas."

cp "$RUNTIME" "$OUT"
echo "===== SCARLETNX MODIFICADO PRONTO ====="
ls -lh "$OUT"
echo "===== COMPILANDO APK MARIO ====="
cd "$ROOT"
export SCARLETNX_PATCHED_RUNTIME_SO="$OUT"
bash compilar-mario-snx-runtime-termux.sh
