#!/usr/bin/env python3
"""Static checks for the exact legal assets packaged into Neo APKs.

This verifies repository content, not completeness of legal compliance for
public distribution. Run before Termux native compilation.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from termux_compile_id import original_build_text

required = {
    "RadialGamePad-GPL-3.0.txt": "GNU GENERAL PUBLIC LICENSE",
    "Ryujinx-Neo-MIT.txt": "MIT License",
    "AndroidX-Apache-2.0.txt": "Apache License",
    "SDL3-zlib.txt": "Sam Lantinga",
    "AdrenoTools-BSD-2-Clause.txt": "BSD 2-Clause",
    "FFmpeg-LGPL-2.1.txt": "LESSER GENERAL PUBLIC LICENSE",
    "Volk-MIT.txt": "Permission is hereby granted",
    "VMA-MIT.txt": "Permission is hereby granted",
    "Dear-ImGui-MIT.txt": "Permission is hereby granted",
    "SMAA-MIT.txt": "Permission is hereby granted",
    "THIRD_PARTY_NOTICES.txt": "RadialGamePad",
}
for name, phrase in required.items():
    path = ROOT / "android/licenses" / name
    assert path.is_file() and path.stat().st_size > 100, f"Missing license: {name}"
    assert phrase in path.read_text(errors="replace"), f"License {name} does not contain {phrase!r}"

script = (ROOT / "compilar-lasrecomp-termux.sh").read_bytes()
assert script.count(b"# BEGIN LICENSE_ASSET_PACKAGING\n") == 2
assert script.count(b"# END LICENSE_ASSET_PACKAGING\n") == 2
assert b'tools/neo_license_manifest.py' in script
assert b'"assets/licenses/RadialGamePad-GPL-3.0.txt"' in script
assert b'"assets/licenses/SOURCE_VERSION.txt"' in script

restored = original_build_text(script)
assert b'HASH="$(sha256sum "$0" | cut -d\' \' -f1)"' in restored
assert b"LICENSE_ASSET_PACKAGING" not in restored

# Legal-only edits must preserve the current native fingerprint. Functional
# changes (including a new game profile) must still invalidate stale objects;
# comparing every future script to one historical commit would reject those.
with tempfile.TemporaryDirectory(prefix="las-license-hash-") as tmp:
    path = Path(tmp) / "build.sh"

    def fingerprint(content):
        path.write_bytes(content)
        return subprocess.check_output(
            [sys.executable, str(ROOT / "tools/termux_compile_id.py"), str(path)]
        ).strip()

    current = fingerprint(script)
    legal_edit = script.replace(b"# BEGIN LICENSE_ASSET_PACKAGING\n",
        b"# BEGIN LICENSE_ASSET_PACKAGING\n# An additional license notice.\n", 1)
    assert fingerprint(legal_edit) == current, "Legal packaging invalidated native objects"
    native_edit = script.replace(b'"$compiler" -O2 -fPIC', b'"$compiler" -O3 -fPIC', 1)
    assert native_edit != script, "Native compiler flags were not found"
    assert fingerprint(native_edit) != current, "Changed native flags reused stale objects"
print("OK: legal-only edits preserve the native fingerprint; compiler changes invalidate it.")

print(f"OK: {len(required)} upstream license/notice documents and APK packaging checks.")
print("Note: these files alone do NOT clear combined GPL/LGPL distribution obligations.")
