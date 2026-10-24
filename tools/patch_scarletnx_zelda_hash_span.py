#!/usr/bin/env python3
"""Adapt range-qualified hash reads to the pinned Vulkan audit runtime.

Inspired by nxnative's per-span resource qualification; use ScarletNX's own
GMMU, page-rounded ownership proof and visibility hooks. No dirty-page guess,
sampled hash, changed hash algorithm, new GPU wait or shader change.
Apply after telemetry; restore before telemetry. Runtime option defaults OFF.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAIRS = {
    'src/nx/gpu/vk/texture.c': [
        ('#include "nx/memory/own.h"',
         '#include "nx/memory/own.h"\n#include "nx/gpu/vk/snx_hash_span.h"'),
        ('    u8* p = __atomic_load_n(&g_own_any, __ATOMIC_ACQUIRE) ? NULL : gmem_ptr(gva, size);',
         '    u8* p = __atomic_load_n(&g_own_any, __ATOMIC_ACQUIRE)\n'
         '                ? snx_hash_span_ptr(gva, size) : gmem_ptr(gva, size);'),
    ],
    'src/nx/gpu/vk/renderer.c': [
        ('    snx_gfx_init();', '    snx_gfx_init();\n    snx_hash_span_init();'),
        ('if (window) { snx_perf_vk_snapshot(window); snx_gfx_report(window); }',
         'if (window) { snx_perf_vk_snapshot(window); snx_gfx_report(window); snx_hash_span_report(window); }'),
    ],
    'src/nx/runtime/snx_perf.h': [
        ('void snx_gfx_report(u64 window);',
         'void snx_gfx_report(u64 window);\nvoid snx_hash_span_init(void);\nvoid snx_hash_span_report(u64 window);'),
    ],
}


def apply(root, revert=False):
    updates = {}
    for name, pairs in PAIRS.items():
        path = root / name
        text = path.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1: continue
            if revert and new not in text and text.count(old) == 1: continue
            a, b = (new, old) if revert else (old, new)
            if text.count(a) != 1:
                raise ValueError('unknown pinned hash-span source; no files changed: ' + name)
            text = text.replace(a, b, 1)
        updates[path] = text
    for path, text in updates.items():
        if path.read_text() != text: path.write_text(text)
    header = root / 'src/nx/gpu/vk/snx_hash_span.h'
    if revert: header.unlink(missing_ok=True)
    else:
        data = (HERE / 'zelda-perf/hash_span.h').read_bytes()
        if not header.exists() or header.read_bytes() != data: header.write_bytes(data)
    print('Zelda range-qualified texture hash:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
