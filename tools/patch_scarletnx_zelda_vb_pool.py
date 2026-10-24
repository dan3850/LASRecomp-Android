#!/usr/bin/env python3
"""Retirement-safe reuse for buffer.c's stable vertex/index/storage buffers.

VkOwnRes pooling already exists: do not reimplement it. Apply after WW evidence.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_shadow_init(void);', 'void snx_shadow_init(void);\nint snx_vb_pool_on(void);\nvoid snx_vb_pool_report(u64 window);'),
        ],
        'src/nx/gpu/vk/buffer.c': [
            ('static void drop_own(Vb* e) {', '#include "nx/gpu/vk/snx_vb_pool.h"\n\nstatic void drop_own(Vb* e) {'),
            ('        vk_defer_buffer(e->buf, e->mem);\n        own_unlink(e);',
             '        snx_vb_release(e->buf, e->mem, e->len);\n        own_unlink(e);'),
            ('    if (vmaCreateBuffer(g_vk.vma, &bci, &aci, &b, &m, NULL) != VK_SUCCESS) return 0;',
             '    if (!snx_vb_allocate(&bci, &aci, &b, &m)) return 0;'),
            ('        vmaDestroyBuffer(g_vk.vma, b, m);\n        return 0;\n    }\n    memcpy(p, src, len);',
             '        snx_vb_abandon(b, m);\n        return 0;\n    }\n    memcpy(p, src, len);'),
            ('    u64 freed = snx_transfer_reclaim(want);',
             '    u64 freed = snx_transfer_reclaim(want);\n    if (freed < want) freed += snx_vb_reclaim(want - freed);'),
            ('    *count = g_own.n;\n    *bytes = g_own.bytes;\n}',
             '    *count = g_own.n + snx_vb_idle_n;\n    *bytes = g_own.bytes + snx_vb_idle_bytes;\n}'),
            ('    snx_transfer_frame();\n    if (g_vk_present % 4) return;',
             '    snx_transfer_frame();\n    snx_vb_frame();\n    if (g_vk_present % 4) return;'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    if (snx_perf_on) snx_ww_report();', '    if (snx_perf_on) snx_ww_report();\n    snx_vb_pool_on();'),
            ('snx_ww_report(); }', 'snx_ww_report(); snx_vb_pool_report(window); }'),
        ],
    }


def apply(root, revert=False):
    updates = {}
    for name, pairs in replacements().items():
        p = root / name; text = p.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1: continue
            if revert and new not in text and text.count(old) == 1: continue
            before, after = (new, old) if revert else (old, new)
            if text.count(before) != 1: raise ValueError('Unknown persistent-buffer source; no changes: ' + name)
            text = text.replace(before, after, 1)
        updates[p] = text
    p = root / 'src/nx/gpu/vk/snx_vb_pool.h'
    data = (HERE / 'zelda-perf/vb_pool.h').read_text()
    if p.exists() and p.read_text() != data: raise ValueError('Unknown persistent-buffer header')
    for path, text in updates.items():
        if path.read_text() != text: path.write_text(text)
    if revert: p.unlink(missing_ok=True)
    elif not p.exists(): p.write_text(data)
    print('Zelda persistent vertex/index/storage buffers:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
