#!/usr/bin/env python3
"""Patch the pinned GPL ScarletNX fs.c to graft a trusted external RomFS.

Usage:
    python3 tools/patch_scarletnx_romfs.py PATH_TO_SCARLETNX_SOURCE

Use the *exact source* matching the packaged ScarletNX native runtime.
The patch intentionally fails on upstream changes, rather than editing
similar-looking code without review. Do not suppress fs_tree safety checks.
"""
from pathlib import Path
import sys

ORIGINAL = """    FsTreeResult r = fs_tree_init(&g_hle.fs.tree, g_datadir);
    if (r != FS_TREE_OK) fatal("Could not index game filesystem %s (error %d)", g_datadir, r);
    size_t n = strlen(g_hle.fs.tree.base);"""

PATCHED = """    FsTreeResult r = fs_tree_init(&g_hle.fs.tree, g_datadir);
    if (r != FS_TREE_OK) fatal("Could not index game filesystem %s (error %d)", g_datadir, r);
#ifdef __ANDROID__
    /* RetroAura Android launcher: the extracted RomFS is already on shared
       storage. Graft its *directory* read-only rather than placing a symlink
       under g_datadir (fs_tree_init intentionally rejects symlinks).
       A separate opt-in Android permission is checked by the Java launcher.
       The filesystem scanner still rejects unsafe symlinks/hardlinks in source. */
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
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target = Path(sys.argv[1]) / "src/nx/hle/filesystem/fs.c"
    text = target.read_text()
    if text.count(PATCHED) == 1:
        print("Already patched:", target)
        return
    if text.count(ORIGINAL) != 1:
        raise SystemExit("ScarletNX source differs from pinned 34853ee; refusing patch")
    if '#include <stdlib.h>' not in text:
        # fs.c already uses malloc/free and standard includes via fs.h; make
        # getenv declaration explicit to avoid implicit-declaration failures.
        text = '#include <stdlib.h>\n' + text
    text = text.replace(ORIGINAL, PATCHED, 1)
    target.write_text(text)
    print("Patched ScarletNX external RomFS graft:", target)

if __name__ == "__main__":
    main()
