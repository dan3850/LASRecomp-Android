#!/usr/bin/env bash
# Optional host integration test: needs Clang, FFmpeg CLI and development headers.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/lasrecomp-movie-test.XXXXXX")"
trap 'rm -rf -- "$TEST_TMP"' EXIT
read -r -a TEST_CFLAGS <<< "${FFMPEG_TEST_CFLAGS:-$(pkg-config --cflags libavformat libavcodec libavutil libswscale)}"
read -r -a TEST_LIBS <<< "${FFMPEG_TEST_LIBS:-$(pkg-config --libs libavformat libavcodec libavutil libswscale)}"
mkdir -p "$TEST_TMP/romfs/region_common/movie"
ffmpeg -v error -f lavfi -i 'color=c=blue:s=16x16:r=4' -t 0.5 -c:v libvpx-vp9 \
    "$TEST_TMP/romfs/region_common/movie/test.webm"
"${CC:-clang}" -std=gnu11 -O1 -g -fno-strict-aliasing -Wno-format \
    -Werror=implicit-function-declaration -ffunction-sections -fdata-sections \
    "${TEST_CFLAGS[@]}" "$ROOT/tests/movie_romfs_harness.c" \
    "$ROOT/runtime/romfs_virtual.c" "$ROOT/runtime/romfs_build.c" \
    -Wl,--gc-sections -pthread "${TEST_LIBS[@]}" -lm -o "$TEST_TMP/movie-test"
"$TEST_TMP/movie-test" "$TEST_TMP"
