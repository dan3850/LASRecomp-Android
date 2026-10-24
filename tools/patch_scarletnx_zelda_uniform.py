#!/usr/bin/env python3
"""Adapt immutable graphics-uniform snapshots to the pinned Vulkan runtime.

Apply after transfer telemetry; restore before it. Preserve strict checks,
pending-result handling, guest writes and the existing staging lifetime.
No graphics uniform is promoted through a pass-breaking GPU copy in ON mode.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
GET_OLD = 'static int buf_get(u64 gva, u64 len, VkBuffer* buf, u64* off, int strict) {'
GET_NEW = 'static int buf_get(u64 gva, u64 len, VkBuffer* buf, u64* off, int strict, int stream) {'
TAIL_OLD = '''    if (!e->own && !(e->stable >= 2 && make_own(e, src))) {
        /* changing (or new) data: this frame's staging ring */'''
TAIL_NEW = '''    /* The old snapshot is immutable and still belongs to this submission.
       guest_bytes may submit/land pending work, so recheck the lifetime here. */
    if (stream && same && valid && !e->own && e->buf && e->frame == vk_submit_number()) {
        snx_uniform_counts[SNX_U_REUSED]++;
        snx_uniform_counts[SNX_U_REUSED_BYTES] += len;
        use(e, buf, off);
        return 1;
    }
    if (stream && !e->own && e->stable >= 2) snx_uniform_counts[SNX_U_PROMOTION_BYPASS]++;
    if (!e->own && !(e->stable >= 2 && !stream && make_own(e, src))) {
        /* changing (or new) data: this frame's staging ring */'''
WRAPPER_OLD = 'int vk_buf_get_strict(u64 gva, u64 len, VkBuffer* buf, u64* off) { return buf_get(gva, len, buf, off, 1); }'
WRAPPER_NEW = '''int vk_buf_get_strict(u64 gva, u64 len, VkBuffer* buf, u64* off) { return buf_get(gva, len, buf, off, 1, 0); }
/* Graphics uniforms only: compute/storage reads keep their original policy. */
int vk_buf_get_uniform(u64 gva, u64 len, VkBuffer* buf, u64* off) {
    int stream = snx_uniform_on() && len <= 65536;
    if (stream) snx_uniform_counts[SNX_U_REQUESTS]++;
    return buf_get(gva, len, buf, off, 1, stream);
}'''


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('int vk_buf_get_strict(u64 gva, u64 len, VkBuffer* buf, u64* off); /* no delayed content checks */',
             'int vk_buf_get_strict(u64 gva, u64 len, VkBuffer* buf, u64* off); /* no delayed content checks */\n'
             'int vk_buf_get_uniform(u64 gva, u64 len, VkBuffer* buf, u64* off);\n'
             'int snx_uniform_on(void);\nvoid snx_uniform_report(u64 window);'),
        ],
        'src/nx/gpu/vk/buffer.c': [
            ('#include "nx/gpu/vk/pending_pages.h"',
             '#include "nx/gpu/vk/pending_pages.h"\n#include "nx/gpu/vk/snx_uniform.h"'),
            (GET_OLD, GET_NEW),
            ('    if (e->hash == h && e->stable < 100000)',
             '    const int same = e->hash == h;\n    if (same && e->stable < 100000)'),
            (TAIL_OLD, TAIL_NEW),
            ('        if (copy_stats_on()) g_copy_stage += len;\n        e->frame = vk_submit_number();',
             '        if (copy_stats_on()) g_copy_stage += len;\n'
             '        if (stream) { snx_uniform_counts[SNX_U_STAGED]++; snx_uniform_counts[SNX_U_STAGED_BYTES] += len; }\n'
             '        e->frame = vk_submit_number();'),
            ('int vk_buf_get(u64 gva, u64 len, VkBuffer* buf, u64* off) { return buf_get(gva, len, buf, off, 0); }',
             'int vk_buf_get(u64 gva, u64 len, VkBuffer* buf, u64* off) { return buf_get(gva, len, buf, off, 0, 0); }'),
            (WRAPPER_OLD, WRAPPER_NEW),
        ],
        'src/nx/gpu/vk/render.c': [
            ('    if (!(a ? vk_buf_get_strict(a, sz, buf, off) : vk_buf_copy(a, sz, buf, off))) return 0;',
             '    if (!(a ? vk_buf_get_uniform(a, sz, buf, off) : vk_buf_copy(a, sz, buf, off))) return 0;'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_transfer_on();', '    snx_transfer_on();\n    snx_uniform_on();'),
            ('snx_transfer_report(window); }', 'snx_transfer_report(window); snx_uniform_report(window); }'),
        ],
    }


def apply(root, revert=False):
    updates = {}
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
                raise ValueError('unknown pinned uniform source; no files changed: ' + name)
            text = text.replace(source, target, 1)
        updates[path] = text
    path = root / 'src/nx/gpu/vk/snx_uniform.h'
    header = (HERE / 'zelda-perf/uniform.h').read_text()
    if path.exists() and path.read_text() != header:
        raise ValueError('generated uniform header differs; no files changed: ' + str(path))
    updates[path] = None if revert else header
    for path, text in updates.items():
        if text is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_text() != text:
            path.write_text(text)
    print('Zelda strict immutable uniform snapshots:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
