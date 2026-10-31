#!/usr/bin/env bash
# Stage a complete upstream ScarletNX checkout without touching the working runtime cache.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
BASE_COMMIT=34853eeae5af132e320adbb0193f13344085bf89
TARGET_COMMIT=05324b57629d0894506b31beb2c72869138b7ad1
BRANCH="$(git branch --show-current)"
[ "$BRANCH" = android/scarletnx-full-upgrade ] || { echo "Use branch android/scarletnx-full-upgrade" >&2; exit 1; }
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
mkdir -p "$(dirname "$SRC")"
if [ ! -d "$SRC/.git" ]; then
  [ ! -e "$SRC" ] || { echo "Destination exists but is not a git checkout: $SRC" >&2; exit 1; }
  git clone --filter=blob:none https://github.com/scarletnx/ScarletNX.git "$SRC"
fi
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "Upgrade source has local modifications; refusing to overwrite" >&2; exit 1; }
git -C "$SRC" fetch origin "$TARGET_COMMIT"
git -C "$SRC" checkout --detach "$TARGET_COMMIT"
ACTUAL="$(git -C "$SRC" rev-parse HEAD)"
[ "$ACTUAL" = "$TARGET_COMMIT" ] || { echo "Unexpected ScarletNX revision" >&2; exit 1; }
echo "Old pinned ScarletNX: $BASE_COMMIT"
echo "Full upstream ScarletNX: $ACTUAL"
echo "New independent source checkout: $SRC"
echo "Existing build source/cache untouched: $HOME/.cache/lasrecomp-scarletnx-romfs/ScarletNX"
echo "NEXT: port and validate Zelda-specific patches against this checkout before building."
