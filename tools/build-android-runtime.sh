#!/usr/bin/env bash
# Link the real upstream LASRecomp engine and UI as an Android ARM64 shared
# library. Does not synthesize guest code or claim that Zelda boots.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ANDROID_NDK_HOME:?ANDROID_NDK_HOME required}"
: "${SDL3_ANDROID_SO:?SDL3_ANDROID_SO required}"
: "${SDL3_ANDROID_HEADERS:?SDL3_ANDROID_HEADERS required}"
: "${SHADERC_OUTPUT_DIR:?SHADERC_OUTPUT_DIR required}"
: "${FFMPEG_INSTALL_DIR:?FFMPEG_INSTALL_DIR required}"
: "${VMA_SRC:?VMA_SRC required}"
TOOL="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
CXX="$TOOL/aarch64-linux-android26-clang++"
READELF="$TOOL/llvm-readelf"
CORE="$ROOT/build/android-runtime-objects/liblasrecomp-core.a"
RENDER="$ROOT/build/android-renderer-objects/liblasrecomp-renderer.a"
FFDIR="$FFMPEG_INSTALL_DIR/lib"
SHADER="$SHADERC_OUTPUT_DIR/libshaderc_shared.so"
BUILDDIR="$ROOT/build/android-linked-runtime"
mkdir -p "$BUILDDIR/ui" "$BUILDDIR/lib/arm64-v8a"
for f in "$CXX" "$CORE" "$RENDER" "$SDL3_ANDROID_SO" "$SHADER"; do
    [[ -s "$f" ]] || { echo "Missing native runtime input $f" >&2; exit 1; }
done

CFLAGS=(-O2 -g -fPIC -fno-strict-aliasing -std=c++17
    -I"$ROOT/runtime" -I"$ROOT/runtime/nvn" -I"$ROOT/runtime/ui"
    -I"$ROOT/third_party/imgui" -I"$ROOT/third_party/imgui/backends"
    -I"$SDL3_ANDROID_HEADERS" -I"$FFMPEG_INSTALL_DIR/include" -I"$VMA_SRC/include")

# .mm is used as a filename by upstream, but the Linux/Android implementation
# is C++ (Objective-C frameworks are guarded by __APPLE__).
OBJECTS=()
FAILED=()
for src in "$ROOT"/runtime/ui/*.mm; do
    obj="$BUILDDIR/ui/$(basename "${src%.mm}").o"
    if "$CXX" "${CFLAGS[@]}" -x c++ -c "$src" -o "$obj"; then
        OBJECTS+=("$obj")
    else
        FAILED+=("$src")
        echo "::warning file=${src#"$ROOT"/}::UI source needs Android port changes"
    fi
done
if (( ${#FAILED[@]} )); then
    printf 'Android UI compile failures (%d):\n' "${#FAILED[@]}"
    printf '  %s\n' "${FAILED[@]}"
    exit 1
fi
echo "Compiled ${#OBJECTS[@]} real C++ UI sources for Android ARM64"

# Require all the engine objects (including HLE section registries), not just
# the small subset referenced by the entry point. The undefined-symbol check
# catches missing renderer dependencies before packaging.
LIB="$BUILDDIR/lib/arm64-v8a/liblasrecomp_runtime.so"
"$CXX" -shared -Wl,-z,max-page-size=16384 -Wl,--no-undefined \
    -Wl,-soname,liblasrecomp_runtime.so \
    -o "$LIB" "${OBJECTS[@]}" "$ROOT/build/android-runtime-objects/hle/movie.o" \
    -Wl,--whole-archive "$CORE" "$RENDER" -Wl,--no-whole-archive \
    -L"$(dirname "$SDL3_ANDROID_SO")" -L"$FFDIR" -L"$SHADERC_OUTPUT_DIR" \
    -lSDL3 -lshaderc_shared -lavformat -lavcodec -lavutil -lswscale \
    -lvulkan -llog -landroid -ldl -lz -lm
"$READELF" -h "$LIB" | grep -q 'AArch64'
echo "FULL_RUNTIME_LINKED=$LIB"
