#!/usr/bin/env python3
"""Observe raster state and color render-target inputs in existing detailed mode.

Apply after viewport depth correction; restore first. No rendering decision changes.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_depth_range_report(u64 window);',
             'void snx_depth_range_report(u64 window);\nvoid snx_lighting_init(void);\nvoid snx_lighting_report(u64 window);'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('#include "nx/runtime/snx_gfx_diag.h"',
             '#include "nx/runtime/snx_gfx_diag.h"\n#include "nx/gpu/vk/snx_lighting_diag.h"'),
            ('        if (snx_gfx_diag_on)\n'
             '            snx_gfx_texture(s, stage, i, &s->si.tex[i], handle, x->tic, x->tsc, t,\n'
             '                            want, num, view, 0);',
             '        if (snx_gfx_diag_on) {\n'
             '            snx_gfx_texture(s, stage, i, &s->si.tex[i], handle, x->tic, x->tsc, t,\n'
             '                            want, num, view, 0);\n'
             '            snx_lighting_texture(s, stage, i, &s->si.tex[i], handle, x->tic, x->tsc, t, want, num, view);\n'
             '        }'),
            ('    /* descriptor sets (may record uploads and barriers, so before the pass opens) */',
             '    if (snx_gfx_diag_on) snx_lighting_state(vs, fs, rt, zt, &k, r);\n'
             '    /* descriptor sets (may record uploads and barriers, so before the pass opens) */'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_depth_range_init();', '    snx_depth_range_init();\n    snx_lighting_init();'),
            ('snx_depth_range_report(window); }',
             'snx_depth_range_report(window); snx_lighting_report(window); }'),
        ],
    }


def apply(root, revert=False):
    updates = {}
    for name, pairs in replacements().items():
        path = root / name; text = path.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1: continue
            if revert and new not in text and text.count(old) == 1: continue
            before, after = (new, old) if revert else (old, new)
            if text.count(before) != 1:
                raise ValueError('Unknown lighting-diagnostic source; no changes: ' + name)
            text = text.replace(before, after, 1)
        updates[path] = text
    header = root / 'src/nx/gpu/vk/snx_lighting_diag.h'
    data = (HERE / 'zelda-perf/lighting_diag.h').read_text()
    if header.exists() and header.read_text() != data: raise ValueError('Unknown lighting-diagnostic header')
    for path, text in updates.items():
        if path.read_text() != text: path.write_text(text)
    if revert: header.unlink(missing_ok=True)
    elif not header.exists(): header.write_text(data)
    print('Zelda lighting composition evidence:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args(); apply(args.source, args.revert)
