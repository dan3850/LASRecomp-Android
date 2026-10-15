#!/usr/bin/env bash
# Build REAL GLSL->SPIR-V shaderc for Android ARM64.
# This is a native dependency of the original LASRecomp Vulkan renderer,
# not a fake Vulkan availability test or a Termux runtime requirement.
set -euo pipefail
: "${ANDROID_NDK_HOME:?Set ANDROID_NDK_HOME}"
: "${SHADERC_SRC:?Set SHADERC_SRC to shaderc v2024.4 checkout}"
: "${SHADERC_OUTPUT_DIR:?Set SHADERC_OUTPUT_DIR}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$SHADERC_OUTPUT_DIR"
TOOLS="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
[[ -x "$TOOLS/aarch64-linux-android26-clang" ]] || { echo "No Android ARM64 clang" >&2; exit 1; }

# These are the upstream pins from shaderc v2024.4's DEPS. Fetch only the
# three dependencies required when examples and tests are disabled.
checkout_dep() {
    local remote="$1" sha="$2" dest="$3"
    if [[ -d "$dest/.git" ]]; then return; fi
    mkdir -p "$dest"
    git -C "$dest" init -q
    git -C "$dest" remote add origin "$remote"
    git -C "$dest" -c advice.detachedHead=false fetch -q --depth=1 origin "$sha"
    git -C "$dest" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
}
checkout_dep https://github.com/KhronosGroup/glslang.git \
    a0995c49ebcaca2c6d3b03efbabf74f3843decdb "$SHADERC_SRC/third_party/glslang"
checkout_dep https://github.com/KhronosGroup/SPIRV-Headers.git \
    3f17b2af6784bfa2c5aa5dbb8e0e74a607dd8b3b "$SHADERC_SRC/third_party/spirv-headers"
checkout_dep https://github.com/KhronosGroup/SPIRV-Tools.git \
    4d2f0b40bfe290dea6c6904dafdf7fd8328ba346 "$SHADERC_SRC/third_party/spirv-tools"

# shaderc v2024.4's third_party CMake sets GLSLANG_ENABLE_INSTALL to
# a generator expression ($<NOT:ON>) instead of a boolean. With Android
# SPIRV-Tools this erroneously generates glslang install(EXPORT) rules for
# SPIRV-Tools-opt, a target which isn't exported. We are building an app
# dependency and do NOT install glslang; disable those rules explicitly.
python3 - "$SHADERC_SRC/third_party/CMakeLists.txt" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'set(GLSLANG_ENABLE_INSTALL $<NOT:${SKIP_GLSLANG_INSTALL}>)'
assert old in s, "shaderc third_party CMake logic changed; inspect before patching"
p.write_text(s.replace(old, 'set(GLSLANG_ENABLE_INSTALL OFF)'))
PY

# Android's APK native-library extraction recognizes lib*.so entries, not
# libshaderc_shared.so.1. Keep the upstream library ABI, but avoid the
# desktop-only versioned SONAME in our private Android build.
python3 - "$SHADERC_SRC/libshaderc/CMakeLists.txt" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'set_target_properties(shaderc_shared PROPERTIES SOVERSION 1)'
assert old in s, "shaderc shared library version settings changed"
p.write_text(s.replace(old, ''))
PY

cmake -S "$SHADERC_SRC" -B "$SHADERC_OUTPUT_DIR/build" \
    -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
    -DANDROID_STL=c++_shared \
    -DCMAKE_BUILD_TYPE=Release \
    -DSHADERC_SKIP_TESTS=ON \
    -DSHADERC_SKIP_EXAMPLES=ON \
    -DSHADERC_SKIP_COPYRIGHT_CHECK=ON \
    -DSHADERC_SKIP_INSTALL=ON \
    -DSPIRV_SKIP_EXECUTABLES=ON \
    -DENABLE_GLSLANG_BINARIES=OFF \
    -DSHADERC_ENABLE_WGSL_OUTPUT=OFF
cmake --build "$SHADERC_OUTPUT_DIR/build" --target shaderc_shared --parallel 4
LIB="$(find "$SHADERC_OUTPUT_DIR/build" -type f -name 'libshaderc_shared.so*' | head -n1)"
[[ -s "$LIB" ]] || { echo "Shaderc shared ARM64 library missing" >&2; exit 1; }
cp "$LIB" "$SHADERC_OUTPUT_DIR/libshaderc_shared.so"

# This is linked by the renderer, not yet by the full runtime.
"$TOOLS/llvm-readelf" -h "$SHADERC_OUTPUT_DIR/libshaderc_shared.so" | grep -q 'AArch64' || {
    echo "shaderc output is not ARM64" >&2
    exit 1
}
echo "shaderc v2024.4 built for Android ARM64: $SHADERC_OUTPUT_DIR/libshaderc_shared.so"
