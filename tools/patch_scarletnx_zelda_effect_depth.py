#!/usr/bin/env python3
"""Capture paired depth and bounded HDR color output for observed Zelda effects.

Apply after lighting diagnostics; restore first. Pixel evidence only, not
a rendering repair. Existing effect-capture switch gates both readbacks.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_lighting_report(u64 window);',
             'void snx_lighting_report(u64 window);\nvoid snx_effect_depth_init(void);\nvoid snx_color_probe_init(void);'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('#include "nx/gpu/vk/snx_shadow_capture.h"',
             '#include "nx/gpu/vk/snx_shadow_capture.h"\n#include "nx/gpu/vk/snx_effect_depth.h"\n#include "nx/gpu/vk/snx_color_probe.h"'),
            ('        const Surf* sampled = view ? t : NULL; /* the texture whose own view is bound, for the sampler */',
             '        if (snx_effect_depth_on && view && !st->shadow && want == VK_IMAGE_VIEW_TYPE_2D)\n'
             '            snx_effect_depth_capture(s, stage, i, zt, t, x->tic, x->tsc, r);\n'
             '        const Surf* sampled = view ? t : NULL; /* the texture whose own view is bound, for the sampler */'),
            ('    if (snx_shadow_enabled) snx_shadow_note(zt, vs, fs, r, ch->render_pred);',
             '    if (snx_shadow_enabled) snx_shadow_note(zt, vs, fs, r, ch->render_pred);\n'
             '    snx_color_probe_after_draw(fs, rt[0], writes);'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_lighting_init();', '    snx_lighting_init();\n    snx_effect_depth_init();\n    snx_color_probe_init();'),
        ],
    }


def legacy_replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            'void snx_lighting_report(u64 window);\nvoid snx_effect_depth_init(void);',
        ],
        'src/nx/gpu/vk/render.c': [
            '#include "nx/gpu/vk/snx_shadow_capture.h"\n#include "nx/gpu/vk/snx_effect_depth.h"',
            None,
            None,
        ],
        'src/nx/gpu/vk/renderer.c': [
            '    snx_lighting_init();\n    snx_effect_depth_init();',
        ],
    }


def apply(root, revert=False):
    updates = {}
    for name, pairs in replacements().items():
        legacy = legacy_replacements()[name]
        path = root / name
        value = path.read_text()
        for index in reversed(range(len(pairs))) if revert else range(len(pairs)):
            old, new = pairs[index]
            if not revert and value.count(new) == 1: continue
            before, after = (new, old) if revert else (old, new)
            if revert and value.count(new) != 1:
                previous = legacy[index]
                if previous and value.count(previous) == 1:
                    before = previous
                elif value.count(old) == 1:
                    continue
            if value.count(before) != 1:
                raise ValueError('Unknown effect-depth source; no changes: ' + name)
            value = value.replace(before, after, 1)
        updates[path] = value
    header = root / 'src/nx/gpu/vk/snx_effect_depth.h'
    payload = (HERE / 'zelda-perf/effect_depth.h').read_text()
    if header.exists() and header.read_text() != payload:
        raise ValueError('Unknown effect-depth header; no changes')
    color = root / 'src/nx/gpu/vk/snx_color_probe.h'
    color_payload = (HERE / 'zelda-perf/color_probe.h').read_text()
    if color.exists() and color.read_text() != color_payload:
        raise ValueError('Unknown color-probe header; no changes')
    for path, value in updates.items():
        if path.read_text() != value: path.write_text(value)
    if revert:
        header.unlink(missing_ok=True)
        color.unlink(missing_ok=True)
    else:
        if not header.exists(): header.write_text(payload)
        if not color.exists(): color.write_text(color_payload)
    print('Zelda paired soft-effect depth evidence:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
