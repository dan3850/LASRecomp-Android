#!/usr/bin/env python3
"""Static checks for the exact legal assets packaged into Neo APKs.

This verifies repository content, not completeness of legal compliance for
public distribution. Run before Termux native compilation.
"""
from pathlib import Path
import subprocess
import sys

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

# On a non-shallow checkout, confirm the license-only edits preserve the exact
# native compile fingerprint of the last build before the notice packaging.
base = subprocess.run(
    ["git", "-C", str(ROOT), "show",
     "8388762460f719615fc3c2c3d97682bcc8aad2e1:compilar-lasrecomp-termux.sh"],
    capture_output=True, check=False,
)
if base.returncode == 0:
    assert restored == base.stdout, (
        "Legal packaging changed the native build's original fingerprint"
    )
    print("OK: native compile fingerprint unchanged from previous Neo build.")
else:
    print("INFO: old Git revision unavailable (shallow clone); structural cache check passed.")

print(f"OK: {len(required)} upstream license/notice documents and APK packaging checks.")
print("Note: these files alone do NOT clear combined GPL/LGPL distribution obligations.")
