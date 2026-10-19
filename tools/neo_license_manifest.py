#!/usr/bin/env python3
"""Preserve legal metadata for all pinned RadialGamePad/AndroidX/Kotlin JARs.

Usage: neo_license_manifest.py STAGED_LICENSES_DIR ARTIFACTS_TSV
Pure packaging step: no network, no dependency downloads, no cache mutation.
"""
from pathlib import Path
import re
import sys
import zipfile

from neo_radial_deps import ARTIFACTS

LEGAL_NAME = re.compile(r"^(?:LICENSE|LICENCE|NOTICE|COPYING)(?:[._-].*)?$", re.I)
MAX_TEXT_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: neo_license_manifest.py LICENSE_DIR ARTIFACTS_TSV", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    tsv = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rows = [line.split("\t") for line in tsv.read_text().splitlines() if line.strip()]
    if len(rows) != len(ARTIFACTS):
        raise RuntimeError("Pinned component list does not match resolved JAR/AAR artifacts")

    manifest = [
        "LASRecomp Android — Neo APK bundled Maven components",
        "This list is generated from the actual pinned runtime artifacts.",
        "Licenses: see THIRD_PARTY_NOTICES.txt and accompanying exact license texts.",
        "",
    ]
    total_bytes = 0
    extracted = 0

    for i, ((group, name, version, extension), row) in enumerate(zip(ARTIFACTS, rows), 1):
        if len(row) != 3:
            raise RuntimeError(f"Malformed artifact manifest row {i}")
        kind, path, _namespace = row
        if kind != extension:
            raise RuntimeError(f"Artifact type mismatch: {group}:{name}:{version}")
        archive = Path(path)
        if not archive.is_file():
            raise RuntimeError(f"Artifact absent: {archive}")
        if group.startswith("com.github."):
            origin = f"https://jitpack.io/#Swordfish90/RadialGamePad/{version}"
            license_label = "GPL-3.0-or-later"
        elif group.startswith("androidx."):
            origin = "https://developer.android.com/jetpack/androidx"
            license_label = "Apache-2.0 (verify embedded notices)"
        else:
            origin = "https://repo.maven.apache.org/maven2/" + group.replace(".", "/") + "/" + name + "/" + version
            license_label = "See upstream artifact notices (Apache-2.0 typical)"
        manifest.append(f"{i:02d}. {group}:{name}:{version} ({extension})")
        manifest.append(f"    License: {license_label}")
        manifest.append(f"    Source: {origin}")

        # The dex compiler drops META-INF when merging classes. Copy any
        # distributor-supplied NOTICE/LICENSE files into APK assets verbatim.
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if info.is_dir() or info.file_size > MAX_TEXT_BYTES:
                    continue
                parts = info.filename.split("/")
                if not parts or parts[0].upper() != "META-INF":
                    continue
                if not any(LEGAL_NAME.fullmatch(part) for part in parts[1:]):
                    continue
                if total_bytes + info.file_size > MAX_TOTAL_BYTES:
                    raise RuntimeError("Embedded license metadata exceeds the safety limit")
                original = z.read(info)
                safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", info.filename)
                target = out / "embedded" / f"{i:02d}-{name}-{version}" / safe_name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
                manifest.append(f"    Embedded notice: {target.relative_to(out).as_posix()}")
                total_bytes += len(original)
                extracted += 1
    manifest.append("")
    manifest.append(f"Preserved embedded notices: {extracted}")
    (out / "NEO_COMPONENTS.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"Neo license manifest: {len(rows)} artifacts, {extracted} embedded legal notices")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"ERROR generating Neo license manifest: {error}", file=sys.stderr)
        raise SystemExit(1)
