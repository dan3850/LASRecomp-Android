#!/usr/bin/env python3
"""Apply only the external RomFS graft to ScarletNX 05324b5.

Usage: python3 tools/patch_scarletnx_romfs_2026.py SCARLETNX_SOURCE [--check]
The --check mode validates compatibility without modifying upstream.
"""
from pathlib import Path
import subprocess
import sys

UPSTREAM = "05324b57629d0894506b31beb2c72869138b7ad1"
ANCHOR = """    if (r != FS_TREE_OK) fatal("Could not index game filesystem %s (error %d)", g_datadir, r);
    size_t n = strlen(g_hle.fs.tree.base);"""
INSERT = """    if (r != FS_TREE_OK) fatal("Could not index game filesystem %s (error %d)", g_datadir, r);
#ifdef __ANDROID__
    /* Android Zelda launcher: mount an explicitly supplied extracted RomFS.
       fs_tree_graft performs the existing host-tree safety validation. */
    const char* external_romfs = getenv("SNX_EXTERNAL_ROMFS");
    if (external_romfs && external_romfs[0]) {
        FsNode* existing = NULL;
        if (!fs_tree_lookup(&g_hle.fs.tree, NULL, "romfs", &existing))
            fatal("External RomFS requested but game data already contains romfs");
        r = fs_tree_graft(&g_hle.fs.tree, "romfs", external_romfs);
        if (r != FS_TREE_OK)
            fatal("Could not graft external RomFS %s (error %d)", external_romfs, r);
        LOG("fs: external RomFS grafted from %s\\n", external_romfs);
    }
#endif
    size_t n = strlen(g_hle.fs.tree.base);"""

def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--check"):
        raise SystemExit(__doc__)
    src = Path(sys.argv[1]).expanduser().resolve()
    revision = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
    if revision != UPSTREAM:
        raise SystemExit(f"Revision mismatch: {revision}; expected {UPSTREAM}")
    target = src / "src/nx/hle/filesystem/fs.c"
    data = target.read_text()
    if data.count(INSERT) == 1:
        print("RomFS graft already present")
        return
    if data.count(ANCHOR) != 1 or '#include <stdlib.h>' not in data:
        raise SystemExit("Upstream fs.c differs from audited source; refusing to patch")
    if len(sys.argv) == 3:
        print("CHECK OK: new ScarletNX RomFS graft anchor compatible")
        return
    target.write_text(data.replace(ANCHOR, INSERT, 1))
    print("Applied external RomFS graft to new ScarletNX:", target)

if __name__ == "__main__":
    main()
