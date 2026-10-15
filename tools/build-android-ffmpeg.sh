#!/usr/bin/env bash
# Build the original runtime's FFmpeg dependency for Android ARM64.
# No Termux executable is needed or embedded in the APK.
# FFmpeg source (LGPL, no --enable-gpl/--enable-nonfree) is provided
# by the CI runner as FFMPEG_SRC; game assets are never bundled.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ANDROID_NDK_HOME:?Set ANDROID_NDK_HOME}"
: "${FFMPEG_SRC:?Set FFMPEG_SRC to FFmpeg n7.1.1 checkout}"
: "${SDL3_ANDROID_HEADERS:?Set SDL3_ANDROID_HEADERS}"

TOOLS="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
CC="$TOOLS/aarch64-linux-android26-clang"
CXX="$TOOLS/aarch64-linux-android26-clang++"
AR="$TOOLS/llvm-ar"
NM="$TOOLS/llvm-nm"
RANLIB="$TOOLS/llvm-ranlib"
STRIP="$TOOLS/llvm-strip"
DEST="$ROOT/build/android-ffmpeg"
OBJDIR="$ROOT/build/android-runtime-objects/hle"
mkdir -p "$DEST" "$OBJDIR"

for f in "$CC" "$AR" "$NM" "$RANLIB" "$STRIP" "$FFMPEG_SRC/configure"; do
    [[ -e "$f" ]] || { echo "Missing Android build input: $f" >&2; exit 1; }
done
(
    cd "$FFMPEG_SRC"
    ./configure \
        --prefix="$DEST" \
        --target-os=android --arch=aarch64 --cpu=armv8-a \
        --enable-cross-compile \
        --cc="$CC" --cxx="$CXX" --ar="$AR" --nm="$NM" --ranlib="$RANLIB" --strip="$STRIP" \
        --sysroot="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot" \
        --enable-pic --disable-doc --disable-programs \
        --disable-static --enable-shared \
        --disable-debug --disable-autodetect --disable-network \
        --disable-everything \
        --enable-avcodec --enable-avformat --enable-avutil --enable-swscale \
        --enable-decoder=aac,h264,hevc,vp8,vp9,vorbis,opus,mp3 \
        --enable-parser=aac,h264,hevc,vp8,vp9,vorbis,opus \
        --enable-demuxer=mov,matroska,ogg,mpegts \
        --enable-protocol=file \
        --extra-cflags="-fPIC" \
        --extra-ldflags="-Wl,-z,max-page-size=16384"
    make -j4
    make install
)

# The original movie HLE module must compile against real FFmpeg Android
# headers, not host libraries or synthetic function declarations.
"$CC" -std=gnu11 -O2 -fPIC -fno-strict-aliasing -Werror=implicit-function-declaration \
    -I"$DEST/include" -I"$ROOT/runtime" -I"$SDL3_ANDROID_HEADERS" \
    -c "$ROOT/runtime/hle/movie.c" -o "$OBJDIR/movie.o"

# Require the real Android output, not just a header-only build.
for lib in avcodec avformat avutil swscale; do
    [[ -s "$DEST/lib/lib${lib}.so" ]] || {
        echo "Missing Android FFmpeg shared library: lib${lib}.so" >&2
        exit 1
    }
done

echo "FFmpeg n7.1.1 ARM64 libraries built; original movie HLE compiled successfully."
echo "Libraries are not yet linked into liblasrecomp_runtime.so; do not claim game boot."
