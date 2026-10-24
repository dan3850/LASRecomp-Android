#!/usr/bin/env python3
"""Adapt persistent transfer buffers and contiguous copies to pinned Vulkan.

Apply after telemetry/hash-span and restore before them. Runtime opt-in only;
the original paths remain available in the same APK. No shader or clock edits.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOC_OLD = '''    if (size > g_vk.alloc_cap || !VK_OK(vmaCreateBuffer(g_vk.vma, &bi, &ai, &r->buf, &r->mem, NULL))) {
        free(r);
        return NULL;
    }'''
ALLOC_NEW = '''    if (size > g_vk.alloc_cap) { free(r); return NULL; }
    VkResult result = vmaCreateBuffer(g_vk.vma, &bi, &ai, &r->buf, &r->mem, NULL);
    /* Only idle, fence-complete resources are reclaimed before retrying. */
    if (result != VK_SUCCESS && snx_transfer_on() && snx_transfer_reclaim(~0ull))
        result = vmaCreateBuffer(g_vk.vma, &bi, &ai, &r->buf, &r->mem, NULL);
    if (!VK_OK(result)) { free(r); return NULL; }'''
RELEASE_OLD = '''    vk_lock();
    vk_defer_buffer(r->buf, r->mem); /* the frame recording may still copy from it */
    vk_unlock();
    free(r);'''
RELEASE_NEW = '''    vk_lock();
    if (snx_transfer_on())
        vk_defer_call(snx_transfer_retire, r); /* pool only AFTER this frame's fence */
    else {
        vk_defer_buffer(r->buf, r->mem);
        free(r);
    }
    vk_unlock();'''
ROWS_OLD = '''    if (!row_bytes) return;
    while (y < rows) {'''
ROWS_NEW = '''    if (!row_bytes) return;
    int reuse = snx_transfer_on();
    if (reuse) snx_transfer_note(SNX_XFER_ROW_BEFORE, ((u64)rows + 63) / 64);
    if (reuse && rows > 1 && src_pitch == row_bytes && dst_pitch == row_bytes &&
        (u64)row_bytes * rows <= ~src_at && (u64)row_bytes * rows <= ~dst_at) {
        VkBufferCopy whole = {src_at, dst_at, (u64)row_bytes * rows};
        rec_CmdCopyBuffer(cb, src, dst, 1, &whole);
        snx_transfer_note(SNX_XFER_ROW_AFTER, 1);
        return;
    }
    while (y < rows) {'''


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('    u32 refs; /* the creator\'s, and one an owned range */',
             '    u32 refs; /* the creator\'s, and one an owned range */\n    u64 generation; /* new content identity on every pool reuse */'),
            ('} VkOwnRes;', '} VkOwnRes;\n#include "nx/gpu/vk/snx_transfer.h"'),
        ],
        'src/nx/gpu/vk/owned.c': [
            ('static int g_own_traps; /* own_init found traps: publishing owns, else it lands */',
             'static int g_own_traps; /* own_init found traps: publishing owns, else it lands */\n'
             '#include "nx/gpu/vk/snx_transfer_impl.h"'),
            ('    VkOwnRes* r = (VkOwnRes*)calloc(1, sizeof *r);',
             '    VkOwnRes* r = snx_transfer_take(size);\n    if (r) return r;\n'
             '    r = (VkOwnRes*)calloc(1, sizeof *r);'),
            (ALLOC_OLD, ALLOC_NEW), (RELEASE_OLD, RELEASE_NEW), (ROWS_OLD, ROWS_NEW),
            ('    r->refs = 1;\n    return r;',
             '    r->refs = 1;\n    r->generation = ++snx_transfer_generation;\n    return r;'),
            ('    OwnHooks h = {own_land, res_retain, res_release, lock_owner};',
             '    OwnHooks h = {own_land, res_retain, res_release, lock_owner, snx_transfer_identity};'),
            ('(u64)(uintptr_t)r[i].res * 0x9E3779B97F4A7C15ull',
             'snx_transfer_identity(r[i].res) * 0x9E3779B97F4A7C15ull'),
            ('        rec_CmdCopyBuffer(cb, src, dst, n, c);',
             '        rec_CmdCopyBuffer(cb, src, dst, n, c);\n'
             '        if (reuse) snx_transfer_note(SNX_XFER_ROW_AFTER, 1);'),
        ],
        'src/nx/memory/own.h': [
            ('    u32 (*busy_tid)(void);',
             '    u32 (*busy_tid)(void);\n'
             '    /* Optional stable identity of this content, distinct across resource reuse. */\n'
             '    u64 (*identity)(void* res);'),
        ],
        'src/nx/memory/own.c': [
            ('        v[2] = (u64)(uintptr_t)o->res;',
             '        v[2] = g_hooks.identity ? g_hooks.identity(o->res) : (u64)(uintptr_t)o->res;'),
        ],
        'src/nx/gpu/vk/dma.c': [
            ('static int dma(const GpuDmaOp* o) {',
             '#include "nx/gpu/vk/snx_transfer_dma.h"\n\n'
             'static int dma(const GpuDmaOp* o) {\n'
             '    int direct = snx_transfer_linear_dma(o);\n    if (direct >= 0) return direct;'),
        ],
        'src/nx/gpu/vk/buffer.c': [
            ('u64 vk_buf_reclaim(u32 before, u64 want) {\n    u64 freed = 0;',
             'u64 vk_buf_reclaim(u32 before, u64 want) {\n    u64 freed = snx_transfer_reclaim(want);'),
            ('void vk_buf_frame(void) {\n    if (g_vk_present % 4) return;',
             'void vk_buf_frame(void) {\n    snx_transfer_frame();\n    if (g_vk_present % 4) return;'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_hash_span_init();', '    snx_hash_span_init();\n    snx_transfer_on();'),
            ('snx_hash_span_report(window); }', 'snx_hash_span_report(window); snx_transfer_report(window); }'),
        ],
    }


def apply(root, revert=False):
    updated = {}
    for name, pairs in replacements().items():
        path = root / name
        text = path.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1:
                continue
            if revert and new not in text and text.count(old) == 1:
                continue
            source, target = (new, old) if revert else (old, new)
            if text.count(source) != 1:
                raise ValueError('unknown pinned transfer source; no files changed: ' + name)
            text = text.replace(source, target, 1)
        updated[path] = text
    dest = root / 'src/nx/gpu/vk'
    for name in ['transfer', 'transfer_impl', 'transfer_dma']:
        path = dest / ('snx_' + name + '.h')
        data = (HERE / 'zelda-perf' / (name + '.h')).read_text()
        if path.exists() and path.read_text() != data:
            raise ValueError('generated transfer header differs; no files changed: ' + str(path))
        updated[path] = None if revert else data
    for path, text in updated.items():
        if text is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_text() != text:
            path.write_text(text)
    print('Zelda persistent transfers/contiguous copies:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
