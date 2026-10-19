#!/usr/bin/env python3
"""Embed SMAA.hlsl as adjacent C string literals without malformed newlines.

Each input line (including its newline) is escaped as a single C string.
All non-ASCII bytes are replaced with '?' to match the historical Termux
build pipeline.  The original shader and Vulkan runtime remain untouched.
"""
import json
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: embed_smaa_hlsl.py INPUT.hlsl OUTPUT.inc", file=sys.stderr)
        return 2
    source = pathlib.Path(sys.argv[1])
    destination = pathlib.Path(sys.argv[2])
    raw = source.read_bytes().replace(b"\r", b"")
    safe = bytes(ch if ch < 128 else ord("?") for ch in raw)
    # json.dumps escapes quotes, backslashes, literal newlines and other
    # controls using syntax valid for C string literals.
    lines = safe.decode("ascii").splitlines(keepends=True)
    if not lines:
        lines = [""]
    output = "".join(json.dumps(line, ensure_ascii=True) + "\n" for line in lines)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(output, encoding="ascii")
    temp.replace(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
