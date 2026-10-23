#!/data/data/com.termux/files/usr/bin/bash
# Read-only version verification before attempting Zelda Stable 60fps v3.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
python3 "$ROOT/tools/zelda_stable60_v3_probe.py" "$@"
