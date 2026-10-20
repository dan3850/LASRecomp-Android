#!/usr/bin/env bash
# Validate the isolated nxnative Android portability components.
# Does not build or launch the game.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="${CC:-cc}"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
CFLAGS=(-std=c11 -Wall -Wextra -Werror -pthread)
INCLUDE=(-I"$ROOT/experimental/nxnative")
echo "[1/3] pthread TLS"
"$CC" "${CFLAGS[@]}" "${INCLUDE[@]}" "$ROOT/tests/nxnative_android_tls_test.c" -o "$OUT/tls"
"$OUT/tls"
echo "[2/3] guest TLS"
"$CC" "${CFLAGS[@]}" "${INCLUDE[@]}" "$ROOT/tests/nxnative_guest_tls_test.c" "$ROOT/experimental/nxnative/android_guest_tls.c" -o "$OUT/guest"
"$OUT/guest"
echo "[3/3] memory image"
"$CC" "${CFLAGS[@]}" "${INCLUDE[@]}" "$ROOT/tests/nxnative_android_image_test.c" "$ROOT/experimental/nxnative/android_image.c" -o "$OUT/image"
"$OUT/image"
echo "NXNATIVE_ANDROID_SMOKE_OK"
