#!/usr/bin/env python3
"""Passive write-watch failure evidence on pinned POSIX source.

Apply after shadow capture; restore before it. No tracking policy change.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/runtime/platform/plat.h': [
            ('int plat_ww_scan(u8* p, u64 size, void (*cb)(u8* p, u64 size));',
             'int plat_ww_scan(u8* p, u64 size, void (*cb)(u8* p, u64 size));\n'
             '#if defined(__linux__)\nvoid snx_ww_report(void);\n#else\nstatic inline void snx_ww_report(void) {}\n#endif'),
        ],
        'src/nx/runtime/platform/plat_posix.c': [
            ('static int g_pagemap = -1;',
             'static int g_pagemap = -1;\n#include "nx/runtime/platform/snx_ww_diag.h"'),
            ('    return ioctl(g_uffd, UFFDIO_REGISTER, &reg) ? -1 : 0;',
             '    int result = ioctl(g_uffd, UFFDIO_REGISTER, &reg);\n'
             '    if (result) snx_ww_note("register_failed", errno, reg.mode, 0);\n'
             '    return result ? -1 : 0;'),
            ('    if (fd < 0) return -1;\n    memset(&api, 0, sizeof api);',
             '    if (fd < 0) { snx_ww_note("userfaultfd_failed", errno, features, 0); return -1; }\n'
             '    memset(&api, 0, sizeof api);'),
            ('    if (ioctl((int)fd, UFFDIO_API, &api)) {\n        close((int)fd);',
             '    if (ioctl((int)fd, UFFDIO_API, &api)) {\n'
             '        snx_ww_note("api_failed", errno, features, api.features);\n        close((int)fd);'),
            ('    return (int)fd;\n}\n#endif\n\n/* One userfaultfd',
             '    snx_ww_note("api_ready", 0, features, api.features);\n'
             '    return (int)fd;\n}\n#endif\n\n/* One userfaultfd'),
            ('    u64 wp = no_ww ? 0 : UFFD_FEATURE_WP_ASYNC | UFFD_FEATURE_WP_UNPOPULATED;',
             '    u64 wp = no_ww ? 0 : UFFD_FEATURE_WP_ASYNC | UFFD_FEATURE_WP_UNPOPULATED;\n'
             '    snx_ww_note(no_ww ? "disabled_by_env" : "init", 0, wp, 0);'),
            ('    if (pm < 0) {\n        struct uffdio_range r = {(u64)(uintptr_t)p, size};',
             '    if (pm < 0) {\n        snx_ww_note("pagemap_open_failed", errno, 0, 0);\n'
             '        struct uffdio_range r = {(u64)(uintptr_t)p, size};'),
            ('    g_pagemap = pm;\n#else\n    (void)p;\n    (void)size;\n#endif\n}',
             '    g_pagemap = pm;\n    snx_ww_note("tracking_registered", 0, wp, 0);\n#else\n'
             '    snx_ww_note("build_uapi_unavailable", 0, 0, 0);\n'
             '    (void)p;\n    (void)size;\n#endif\n}'),
            ('    __atomic_store_n(&g_pagemap, -1, __ATOMIC_RELEASE);\n    WARN("memory: could not watch remapped',
             '    __atomic_store_n(&g_pagemap, -1, __ATOMIC_RELEASE);\n'
             '    snx_ww_note("remap_failed", errno, 0, 0);\n    WARN("memory: could not watch remapped'),
            ('        n = ioctl(pm, PAGEMAP_SCAN, &arg);\n        if (n < 0) return -1;',
             '        n = ioctl(pm, PAGEMAP_SCAN, &arg);\n'
             '        if (n < 0) { snx_ww_note("scan_failed", errno, arg.flags, 0); return -1; }'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_shadow_init();', '    snx_shadow_init();\n    if (snx_perf_on) snx_ww_report();'),
            ('snx_bind_reuse_report(window); }', 'snx_bind_reuse_report(window); snx_ww_report(); }'),
        ],
    }


def apply(root, revert=False):
    updates = {}
    for name, pairs in replacements().items():
        p = root / name
        text = p.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1: continue
            if revert and new not in text and text.count(old) == 1: continue
            before, after = (new, old) if revert else (old, new)
            if text.count(before) != 1:
                raise ValueError('Unknown write-watch source; no changes: ' + name)
            text = text.replace(before, after, 1)
        updates[p] = text
    p = root / 'src/nx/runtime/platform/snx_ww_diag.h'
    data = (HERE / 'zelda-perf/ww_diag.h').read_text()
    if p.exists() and p.read_text() != data: raise ValueError('Unknown write-watch header')
    for path, text in updates.items():
        if path.read_text() != text: path.write_text(text)
    if revert: p.unlink(missing_ok=True)
    elif not p.exists(): p.write_text(data)
    print('Zelda write-watch evidence:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
