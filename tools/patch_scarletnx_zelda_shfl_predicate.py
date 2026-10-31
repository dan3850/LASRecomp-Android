#!/usr/bin/env python3
"""Backport the SHFL-to-PT predicate fix from ScarletNX 1ac8360.

The pinned ScarletNX translator uses a boolean direct_writes_pred() instead of
the newer per-predicate bitset. Preserve that ABI and only correct SHFL PT.
"""
import argparse
from pathlib import Path

OLD = """        case O_R2P_I:
        case O_SHFL:
        case O_VOTE: return 1;"""
NEW = """        case O_R2P_I:
        case O_VOTE: return 1;
        /* SHFL only writes its named predicate; PT (7) writes none. */
        case O_SHFL: return B(w, 48, 3) != 7;"""

def apply(root: Path, revert: bool = False) -> None:
    path = root / "src/nx/gpu/shader/spirv_translate.c"
    data = path.read_text()
    before, after = (NEW, OLD) if revert else (OLD, NEW)
    if data.count(after) == 1:
        print("SHFL predicate backport already", "reverted" if revert else "applied")
        return
    if data.count(before) != 1:
        raise ValueError("Unknown ScarletNX shader translator; no changes made")
    path.write_text(data.replace(before, after, 1))
    print("SHFL predicate backport", "reverted" if revert else "applied")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    apply(args.source, args.revert)
