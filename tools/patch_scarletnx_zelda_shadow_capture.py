#!/usr/bin/env python3
"""Bounded depth-aspect snapshots before shadow sampling. Apply after bindings.

No shader, cache, AOT, guest-memory write or wait-policy change. Restore first.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_bind_reuse_report(u64 window);',
             'void snx_bind_reuse_report(u64 window);\nvoid snx_shadow_init(void);'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('#include "nx/runtime/snx_gfx_diag.h"',
             '#include "nx/runtime/snx_gfx_diag.h"\n#include "nx/gpu/vk/snx_shadow_capture.h"'),
            ('        const Surf* sampled = view ? t : NULL; /* the texture whose own view is bound, for the sampler */',
             '        if (snx_shadow_enabled && view && st->shadow && t && t->f.depth && !is_target(t, rt, zt, n))\n'
             '            snx_shadow_capture(s, stage, i, t, x->tic, x->tsc);\n'
             '        const Surf* sampled = view ? t : NULL; /* the texture whose own view is bound, for the sampler */'),
            ('    g_vk_drawn++;\n}',
             '    g_vk_drawn++;\n    if (snx_shadow_enabled) snx_shadow_note(zt, vs, fs, r, ch->render_pred);\n}'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_bind_reuse_on();', '    snx_bind_reuse_on();\n    snx_shadow_init();'),
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
                raise ValueError(f'Unknown or partial shadow capture source: {name}: {source[:80]}')
            text = text.replace(source, target, 1)
        updates[path] = text
    header = root / 'src/nx/gpu/vk/snx_shadow_capture.h'
    payload = (HERE / 'zelda-perf/shadow_capture.h').read_text()
    if header.exists() and header.read_text() != payload:
        raise ValueError(f'Unknown shadow capture header: {header}')
    for path, text in updates.items():
        if path.read_text() != text:
            path.write_text(text)
    if revert:
        header.unlink(missing_ok=True)
    elif not header.exists():
        header.write_text(payload)
    print('Zelda bounded shadow-depth capture:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
