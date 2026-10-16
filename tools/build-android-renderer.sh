#!/usr/bin/env bash
# Cross-compile the REAL LASRecomp NVN->Vulkan backend and Dear ImGui.
# Stage output: static ARM64 archive. Full game runtime linkage is a later
# step; this script does not claim that the game already boots.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ANDROID_NDK_HOME:?Set ANDROID_NDK_HOME to the Android NDK root}"
: "${SDL3_ANDROID_HEADERS:?Set SDL3_ANDROID_HEADERS to the official SDL3 include directory}"
: "${SHADERC_SRC:?Set SHADERC_SRC to the official shaderc source checkout}"
: "${VMA_SRC:?Set VMA_SRC to the VulkanMemoryAllocator source checkout}"
: "${VOLK_SRC:?Set VOLK_SRC to the pinned volk source checkout}"
[[ -s "$VOLK_SRC/volk.h" && -s "$VOLK_SRC/volk.c" ]] || { echo "volk sources missing" >&2; exit 1; }

if [[ -x "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang" ]]; then
    TOOLS="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
else
    echo "ERROR: missing Android NDK ARM64 cross-compiler" >&2
    exit 1
fi

CC="$TOOLS/aarch64-linux-android26-clang"
CXX="$TOOLS/aarch64-linux-android26-clang++"
AR="$TOOLS/llvm-ar"
OBJDIR="$ROOT/build/android-renderer-objects"
mkdir -p "$OBJDIR"

INC=(
    "-I$ROOT/runtime"
    "-I$ROOT/runtime/nvn"
    "-I$ROOT/third_party/imgui"
    "-I$ROOT/third_party/imgui/backends"
    "-I$ROOT/third_party/smaa/Textures"
    "-I$SDL3_ANDROID_HEADERS"
    "-I$SHADERC_SRC/libshaderc/include"
    "-I$VMA_SRC/include"
    "-I$VOLK_SRC"
)

# Reproduce the source-to-C-string transformation the upstream Makefile uses.
mkdir -p "$OBJDIR/inc"
LC_ALL=C tr -d '\r' < "$ROOT/third_party/smaa/SMAA.hlsl" \
    | LC_ALL=C tr '\200-\377' '?' \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/\\n"/' \
    > "$OBJDIR/inc/smaa_hlsl.inc"
INC+=("-I$OBJDIR/inc")

OBJECTS=()
FAILED=()
mapfile -t SOURCES < <(
    find "$ROOT/runtime/nvn/vulkan" -maxdepth 1 -name '*.c' -o -name '*.cpp'
    for src in imgui.cpp imgui_draw.cpp imgui_tables.cpp imgui_widgets.cpp; do
        printf '%s\n' "$ROOT/third_party/imgui/$src"
    done
    for src in imgui_impl_sdl3.cpp imgui_impl_vulkan.cpp; do
        printf '%s\n' "$ROOT/third_party/imgui/backends/$src"
    done
    printf '%s\n' "$ROOT/runtime/nvn/smaa_data.c"
    printf '%s\n' "$ROOT/android/game/png_writer.c"
    printf '%s\n' "$VOLK_SRC/volk.c"
)

for src in "${SOURCES[@]}"; do
    rel="${src#"$ROOT"/}"
    obj="$OBJDIR/$rel.o"
    mkdir -p "$(dirname "$obj")"
    compiler="$CC"
    flags=(-std=gnu11)
    if [[ "$src" == *.cpp ]]; then
        compiler="$CXX"
        flags=(-std=c++17)
    fi
    if "$compiler" "${flags[@]}" -O2 -fPIC -fno-strict-aliasing \
            "-DLASRECOMP_BUILD_SHA=\"$(git -C "$ROOT" rev-parse --short=12 HEAD)\"" \
            -D_FILE_OFFSET_BITS=64 -DVK_NO_PROTOTYPES -DIMGUI_IMPL_VULKAN_USE_VOLK -Wno-nullability-completeness -Werror=implicit-function-declaration \
            "${INC[@]}" -c "$src" -o "$obj"; then
        OBJECTS+=("$obj")
    else
        FAILED+=("$rel")
        echo "::warning file=$rel::Android renderer source failed to compile"
    fi
done

if (( ${#FAILED[@]} )); then
    printf 'Renderer sources requiring Android changes (%d):\n' "${#FAILED[@]}"
    printf '  %s\n' "${FAILED[@]}"
    exit 1
fi

"$AR" rcs "$OBJDIR/liblasrecomp-renderer.a" "${OBJECTS[@]}"
echo "Compiled ${#OBJECTS[@]} original Vulkan/ImGui/SMAA modules for Android ARM64"
echo "Archive: $OBJDIR/liblasrecomp-renderer.a (NOT YET linked into game runtime)"
