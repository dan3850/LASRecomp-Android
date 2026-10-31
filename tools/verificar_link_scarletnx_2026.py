#!/usr/bin/env python3
"""Fail-closed Android linker compatibility gate for ScarletNX 05324b5.

Checks whether the old LASRecomp linker injection can be safely reused.
Does not edit sources or generate a binary.
"""
from pathlib import Path
import subprocess
import sys
if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 tools/verificar_link_scarletnx_2026.py SOURCE")
src = Path(sys.argv[1]).expanduser().resolve()
revision = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
if revision != "05324b57629d0894506b31beb2c72869138b7ad1":
    raise SystemExit("Unexpected ScarletNX revision")
cmake = (src / "src/nx/CMakeLists.txt").read_text()
entry = (src / "src/nx/runtime/entry.c").read_text()
checks = {
    "Old linker -Bsymbolic anchor": cmake.count("    target_link_options(scarletnx PRIVATE -Wl,-Bsymbolic)\n") == 1,
    "Old main() trace anchor": entry.count("int main(int argc, char** argv) {\n") == 1,
    "Old entry include anchor": entry.count("#include <string.h>\n") == 1,
}
for name, ok in checks.items():
    print(f"{'COMPATIVEL' if ok else 'INCOMPATIVEL'}: {name}")
if not all(checks.values()):
    print("BLOCKED: old patch_scarletnx_android_link.py must not be applied to new upstream.")
    print("Port linker options and boot trace against new entry points first.")
    sys.exit(2)
print("Old linker patch anchors present; further ABI and ELF validation still required.")
