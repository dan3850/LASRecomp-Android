#!/usr/bin/env python3
"""Safely extract the Ryujinx Android ARM64 GitHub Actions native binary.

No Android permissions, installation, APK edits, or network calls.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import sys
import zipfile

SONAME = "libRyujinxShaderNative.so"
MAX_SO = 128 * 1024 * 1024


def extract(archive: Path, dest: Path):
    with zipfile.ZipFile(archive) as z:
        files = {Path(i.filename).name: i for i in z.infolist()
                 if not i.is_dir() and Path(i.filename).name in
                 (SONAME, "SHA256SUMS", "README.txt")}
        if SONAME not in files:
            raise ValueError("ZIP is not the Ryujinx NativeAOT artifact: " + str(archive))
        info = files[SONAME]
        if not 1024 <= info.file_size <= MAX_SO:
            raise ValueError("unexpected native library size")
        payload = z.read(info)
        if len(payload) < 64 or payload[:6] != bytes((0x7f, 69, 76, 70, 2, 1)):
            raise ValueError("not a little-endian 64-bit ELF")
        if struct.unpack_from("<H", payload, 16)[0] != 3:
            raise ValueError("native library is not an ELF shared object")
        if struct.unpack_from("<H", payload, 18)[0] != 183:
            raise ValueError("native library is not compiled for ARM64")
        if "SHA256SUMS" in files:
            lines = z.read(files["SHA256SUMS"]).decode("ascii", "replace").splitlines()
            expected = [line.split()[0].lower() for line in lines
                        if line.strip() and Path(line.split()[-1]).name == SONAME]
            if len(expected) != 1 or hashlib.sha256(payload).hexdigest() != expected[0]:
                raise ValueError("SHA-256 integrity check failed")
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".partial")
        try:
            temp.write_bytes(payload)
            temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)
        return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("artifact", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    try:
        path = extract(a.artifact, a.out)
        print("Biblioteca Android ARM64 verificada:", path)
        print("Bytes:", path.stat().st_size)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        ap.error(str(e))


if __name__ == "__main__":
    sys.exit(main())
