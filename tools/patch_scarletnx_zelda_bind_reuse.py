#!/usr/bin/env python3
"""Fast exact lookup of resolved binding state before the existing descriptor cache.

Apply after uniform-extent telemetry; restore before it. All stage resolution,
strict reads, uploads, feedback handling and barriers remain in their old order.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = 'static VkDescriptorSet desc_set_cached(VkDescriptorSetLayout layout, DescWrites* d) {'
NEW = 'static VkDescriptorSet snx_desc_original(VkDescriptorSetLayout layout, DescWrites* d) {'
STAGE = 'static VkDescriptorSet stage_set(GpuChannel* ch, int stage, VkSh* s, Surf** rt, Surf* zt, u32 n, int* zt_ro, u32* fb,'


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_ub_extent_report(u64 window);',
             'void snx_ub_extent_report(u64 window);\nint snx_bind_reuse_on(void);\nvoid snx_bind_reuse_report(u64 window);'),
        ],
        'src/nx/gpu/vk/render.c': [
            (OLD, NEW),
            (STAGE, '#include "nx/gpu/vk/snx_bind_reuse.h"\n\n' + STAGE),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_ub_extent_on();', '    snx_ub_extent_on();\n    snx_bind_reuse_on();'),
            ('snx_ub_extent_report(window); }', 'snx_ub_extent_report(window); snx_bind_reuse_report(window); }'),
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
            a, b = (new, old) if revert else (old, new)
            if text.count(a) != 1:
                raise ValueError('unknown pinned binding-reuse source; no files changed: ' + name)
            text = text.replace(a, b, 1)
        updates[path] = text
    header = root / 'src/nx/gpu/vk/snx_bind_reuse.h'
    data = (HERE / 'zelda-perf/bind_reuse.h').read_text()
    if header.exists() and header.read_text() != data:
        raise ValueError('generated binding-reuse header differs; no files changed: ' + str(header))
    updates[header] = None if revert else data
    for path, text in updates.items():
        if text is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_text() != text:
            path.write_text(text)
    print('Zelda validated binding-state reuse:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
