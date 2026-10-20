#!/usr/bin/env python3
"""Audit nxnative's Apple-specific host dependencies before an Android port.

Usage: python3 tools/nxnative_android_audit.py /path/to/nxnative
This does not build an APK or alter either source tree.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys

RULES = {
    "Apple-only headers/frameworks": re.compile(
        r"#\s*(?:include|import)\s*[<\"](?:TargetConditionals\.h|mach(?:/|-o/)|"
        r"Metal/|Foundation/|UIKit/|AppKit/|VideoToolbox/|CoreAudio/|"
        r"CoreMedia/|CoreVideo/|AudioToolbox/|QuartzCore/|IOSurface/)"
    ),
    "Apple TLS register": re.compile(r"\btpidrro_el0\b"),
    "Apple executable mapping": re.compile(r"\b(?:getsectiondata|_mh_execute_header|"
        r"__TEXT|__DATA_CONST|MAP_JIT|pthread_jit_write_protect_np)\b"),
}
SUFFIXES = {".c", ".h", ".m", ".mm", ".cc", ".cpp", ".hpp"}

def audit(root: Path) -> int:
    host = root / "dm" / "host"
    gfx = root / "dm" / "gfx"
    if not host.is_dir() or not gfx.is_dir():
        print("ERROR: expected nxnative checkout with dm/host and dm/gfx", file=sys.stderr)
        return 2
    totals = {key: 0 for key in RULES}
    for folder in (host, gfx):
        for file in sorted(folder.rglob("*")):
            if file.suffix not in SUFFIXES or not file.is_file():
                continue
            for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for label, pattern in RULES.items():
                    if pattern.search(line):
                        print(f"{file.relative_to(root)}:{number}: {label}: {line.strip()[:150]}")
                        totals[label] += 1
    print("\nDependency counts (occurrences, not engineering estimates):")
    for label, count in totals.items():
        print(f"  {label}: {count}")
    print("Next gate: replace TLS and Mach-O assumptions, then compile host objects for Android ARM64.")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nxnative", type=Path, help="local checkout of seedds/nxnative")
    args = parser.parse_args()
    sys.exit(audit(args.nxnative.resolve()))
