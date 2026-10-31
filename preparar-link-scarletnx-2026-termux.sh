#!/data/data/com.termux/files/usr/bin/bash
# Stage only the Android linker patch for ScarletNX 2026, isolated from stable runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ "$(git branch --show-current)" = android/scarletnx-full-upgrade ] || { echo "ERRO: branch incorreta"; exit 1; }
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
[ -d "$SRC/.git" ] || { echo "Execute primeiro preparar-zelda-scarletnx-limpo-termux.sh"; exit 1; }
[ "$(git -C "$SRC" rev-parse HEAD)" = 05324b57629d0894506b31beb2c72869138b7ad1 ] || { echo "ERRO: revisao incorreta"; exit 1; }
for entry in $(git -C "$SRC" diff --name-only); do
  case "$entry" in
    cmake/llvm.cmake|src/nx/hle/filesystem/fs.c|src/multicall/CMakeLists.txt) ;;
    *) echo "ERRO: alteracao inesperada no upstream: $entry"; exit 1 ;;
  esac
done
[ -n "${PREFIX:-}" ] || { echo "ERRO: execute no Termux"; exit 1; }
if [ -z "${ANDROID_NDK_ROOT:-}" ]; then
  for candidate in "${ANDROID_HOME:-$HOME/Android/Sdk}"/ndk/* "$HOME/android-sdk/ndk/"*; do
    if [ -f "$candidate/build/cmake/android.toolchain.cmake" ]; then
      ANDROID_NDK_ROOT="$candidate"
    fi
  done
fi
[ -n "${ANDROID_NDK_ROOT:-}" ] || { echo "ERRO: NDK ausente"; exit 1; }
LIBC="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/sysroot/usr/lib/aarch64-linux-android/26/libc.so"
[ -s "$LIBC" ] || { echo "ERRO: libc Android26 ausente: $LIBC"; exit 1; }
BASE="$HOME/.cache/lasrecomp-scarletnx-upgrade"
AUDIT="$BASE/link-evidence"
MAP="$BASE/scarletnx-android-symbols.map"
mkdir -p "$AUDIT"
cat > "$MAP.tmp" <<'EOF'
{
  global:
    main;
    JNI_OnLoad;
    Java_*;
    SDL_*;
  local: *;
};
EOF
if ! cmp -s "$MAP.tmp" "$MAP"; then mv -f "$MAP.tmp" "$MAP"; else rm -f "$MAP.tmp"; fi
python3 "$ROOT/tools/patch_scarletnx_android_link_2026.py" "$SRC" --libc "$LIBC" --symbol-map "$MAP" --evidence "$AUDIT" --check
python3 "$ROOT/tools/patch_scarletnx_android_link_2026.py" "$SRC" --libc "$LIBC" --symbol-map "$MAP" --evidence "$AUDIT"
echo "LINK_PATCH_PREPARED: source=$SRC evidence=$AUDIT"
echo "NAO compilado. O linker, ABI e boot ainda exigem validacao."
