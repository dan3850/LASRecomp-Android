#!/usr/bin/env bash
# Private/offline Android ARM64 game-code build for the owner's *extracted*
# Link's Awakening v1.0.0 data. This is a BUILD-HOST tool, not a Termux
# dependency of the installed APK, and it never uploads Nintendo data.
#
# Usage:
#   ANDROID_NDK_HOME=/path/to/ndk \
#   LASRECOMP_RUNTIME_SO=/path/to/liblasrecomp_runtime.so \
#   bash tools/build-android-lasgame.sh /private/path/to/extracted
#
# The resulting private liblasgame.so can be installed only as part of a
# newly signed APK via LASRECOMP_GAME_SO=... in build-android-termux.sh.
# The user-facing app does not yet generate this library on-device.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_DIR="${1:?Specify the extracted game directory containing exefs/main and exefs/sdk}"
: "${ANDROID_NDK_HOME:?Provide the Android NDK for cross compilation}"
: "${LASRECOMP_RUNTIME_SO:?Provide the linked liblasrecomp_runtime.so}"
[[ -s "$LASRECOMP_RUNTIME_SO" ]] || { echo "ARM64 runtime shared library missing" >&2; exit 1; }
for name in main sdk main.npdm; do
    [[ -s "$GAME_DIR/exefs/$name" ]] || { echo "Missing game file exefs/$name" >&2; exit 1; }
done

# Require the v1.0.0 build that the runtime loader understands.
python3 - "$GAME_DIR/exefs/main" <<'PY'
from pathlib import Path
import sys
with Path(sys.argv[1]).open("rb") as f:
    f.seek(0x40)
    got = f.read(8)
if got != bytes.fromhex("ae16f71e002af8cb"):
    raise SystemExit("Only Link's Awakening 1.0.0 (unpatched exefs/main) is supported")
PY

TOOL="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
CC="$TOOL/aarch64-linux-android26-clang"
CXX="$TOOL/aarch64-linux-android26-clang++"
NM="$TOOL/llvm-nm"
READELF="$TOOL/llvm-readelf"
for f in "$CC" "$CXX" "$NM" "$READELF"; do
    [[ -x "$f" ]] || { echo "Required NDK cross-compiler missing: $f" >&2; exit 1; }
done
# tools/gen.py uses the Unicorn Python module on the BUILD machine.
python3 -c 'import unicorn' || {
    echo "The build machine needs Python 3 with the 'unicorn' module to run LASRecomp's generator" >&2
    exit 1
}

OUT="$ROOT/build/private-android-lasgame"
GEN="$OUT/generated"
OBJ="$OUT/objects"
mkdir -p "$GEN/main" "$GEN/sdk" "$OBJ"

# Generate genuine code from the two user-provided NSO modules using the
# upstream LASRecomp generator and the same fixed guest bases as gamebuild.c.
# --simd asm is ARM64 host code, not Switch ARM64 emulation.
python3 "$ROOT/tools/gen.py" main "$GAME_DIR/exefs/main" \
    0x7000000000 "$GEN/main" --simd asm
python3 "$ROOT/tools/gen.py" sdk "$GAME_DIR/exefs/sdk" \
    0x7004000000 "$GEN/sdk" --hle "$ROOT/runtime/hle/hle_symbols.txt" --simd asm

mapfile -d '' -t SOURCES < <(find "$GEN/main" "$GEN/sdk" -maxdepth 1 -type f -name '*.c' -print0 | sort -z)
(( ${#SOURCES[@]} > 2 )) || {
    echo "The generator did not produce the required game source units" >&2
    exit 1
}
SOURCES+=("$ROOT/tools/gamelib_entry.c")

# The Android runtime currently uses the upstream fallback GAMELIB_ID=dev.
# Keep the entry ID in sync with the runtime instead of shipping a silent ABI
# mismatch. Versioned generator hashing remains a later requirement.
ID='dev'
OBJECTS=()
for src in "${SOURCES[@]}"; do
    rel="${src#"$OUT"/}"
    [[ "$src" == "$ROOT/tools/gamelib_entry.c" ]] && rel="gamelib_entry.c"
    obj="$OBJ/$rel.o"
    mkdir -p "$(dirname "$obj")"
    if [[ ! -s "$obj" || "$src" -nt "$obj" || "$ROOT/runtime/cpu.h" -nt "$obj" ||
          "$ROOT/runtime/simd.h" -nt "$obj" || "$ROOT/runtime/gamelib.h" -nt "$obj" ]]; then
        "$CC" -std=gnu11 -O1 -fPIC -fno-strict-aliasing -fvisibility=hidden \
            -Wno-unused-label -Wno-return-type -I"$ROOT/runtime" \
            -DGAMELIB_ID="\"$ID\"" -c "$src" -o "$obj"
    fi
    OBJECTS+=("$obj")
done

LIB="$OUT/liblasgame.so"
"$CXX" -shared -Wl,-z,max-page-size=16384 -Wl,--no-undefined \
    -Wl,-soname,liblasgame.so -o "$LIB" "${OBJECTS[@]}" \
    -L"$(dirname "$LASRECOMP_RUNTIME_SO")" -llasrecomp_runtime \
    -llog -landroid -ldl -lm

"$READELF" -h "$LIB" | grep -q AArch64 || { echo "Not an ARM64 library" >&2; exit 1; }
"$NM" -D --defined-only "$LIB" | grep -Eq '[[:space:]]lasgame_tables$' || {
    echo "The generated game function tables are missing" >&2
    exit 1
}
echo "PRIVATE_GAME_LIBRARY=$LIB"
echo "This library contains code derived from user game files. Keep it PRIVATE."
echo "It cannot be placed in writable Android app data; it must be signed into a private APK."
