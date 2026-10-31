#!/usr/bin/env python3
"""Port Android ELF link flags to ScarletNX 05324b5's new multicall target.

Unlike the old runtime, scarletnx is now defined in src/multicall/CMakeLists.txt.
Only linker hygiene is applied; no old graphics or entrypoint patch is imported.
"""
import argparse
from pathlib import Path
import subprocess
import sys

REV = "05324b57629d0894506b31beb2c72869138b7ad1"
ANCHOR = "    target_link_options(scarletnx PRIVATE -Wl,-Bsymbolic)\n"
BEGIN = "    # BEGIN LASRECOMP_ANDROID_2026_LINK\n"
END = "    # END LASRECOMP_ANDROID_2026_LINK\n"

def safe_path(value):
    path = str(Path(value).resolve())
    if any(c in path for c in ('"', ';', '$', '\n', '\r', '\\')):
        raise ValueError("Unsafe linker path")
    return path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--libc", required=True)
    ap.add_argument("--symbol-map", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    source = a.source.resolve()
    rev = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if rev != REV:
        raise SystemExit("Unexpected ScarletNX revision")
    cmake = source / "src/multicall/CMakeLists.txt"
    data = cmake.read_text()
    if data.count(ANCHOR) != 1:
        raise SystemExit("Multicall linker anchor changed")
    libc = safe_path(a.libc)
    symbol_map = safe_path(a.symbol_map)
    evidence = Path(a.evidence).resolve()
    if not a.check:
        if not Path(libc).is_file() or not Path(symbol_map).is_file():
            raise SystemExit("Missing libc import library or symbol map")
        evidence.mkdir(parents=True, exist_ok=True)
    block = BEGIN + '    target_link_options(scarletnx PRIVATE\n'
    options = [
        "-Wl,--push-state,--no-as-needed", libc, "-Wl,--pop-state",
        "-Wl,--version-script=" + symbol_map,
        "-Wl,-Map=" + safe_path(evidence / "scarletnx.map"),
        "-Wl,--cref",
        "-Wl,--why-extract=" + safe_path(evidence / "why-extract.tsv"),
        "-Wl,--trace-symbol=getauxval",
        "-Wl,--trace-symbol=__aarch64_have_lse_atomics",
    ]
    block += "".join('        "' + item + '"\n' for item in options)
    block += '    )\n'
    block += '    set_property(TARGET scarletnx APPEND PROPERTY LINK_DEPENDS "' + symbol_map + '")\n'
    block += END
    if BEGIN in data or END in data:
        if data.count(BEGIN) != 1 or data.count(END) != 1:
            raise SystemExit("Malformed previous Android link patch")
        before, remainder = data.split(BEGIN, 1)
        _, after = remainder.split(END, 1)
        data = before + after
    data = data.replace(ANCHOR, ANCHOR + block, 1)
    if a.check:
        print("ANDROID_2026_LINK_CHECK_OK: multicall target found")
    else:
        cmake.write_text(data)
        print("ANDROID_2026_LINK_PATCH_OK: " + str(cmake))

if __name__ == "__main__":
    main()
