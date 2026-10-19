#!/usr/bin/env python3
"""Hash only the original native build logic, not license packaging.

Why: the old Termux script SHA256 is stored in build/termux-native/flags.id
and controls compilation of all native object files. Adding legal docs must
not invalidate the native C/C++ cache. We reconstruct the previous script
exactly before calculating the compatibility fingerprint. Changes to other
build logic continue to invalidate stale native objects as before.
"""
import hashlib
from pathlib import Path
import sys

BEG = b"# BEGIN LICENSE_ASSET_PACKAGING\n"
END = b"# END LICENSE_ASSET_PACKAGING\n"
OLD = b"""HASH="$(sha256sum "$0" | cut -d' ' -f1)" """
NEW = b"""HASH="$(python3 tools/termux_compile_id.py "$0")" """


def original_build_text(updated: bytes) -> bytes:
    text = updated
    if text.count(BEG) != text.count(END):
        raise ValueError("Mismatched legal packaging markers")
    while BEG in text:
        first = text.index(BEG)
        last = text.find(END, first + len(BEG))
        if last < 0:
            raise ValueError("Missing license packaging end marker")
        text = text[:first] + text[last + len(END):]
    old = OLD.rstrip()
    new = NEW.rstrip()
    if text.count(new) != 1:
        raise ValueError("Cannot restore original native build hash statement")
    return text.replace(new, old, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: termux_compile_id.py compilar-lasrecomp-termux.sh")
    try:
        original = original_build_text(Path(sys.argv[1]).read_bytes())
    except (OSError, ValueError) as error:
        raise SystemExit(f"ERRO: build fingerprint: {error}")
    print(hashlib.sha256(original).hexdigest())


if __name__ == "__main__":
    main()
