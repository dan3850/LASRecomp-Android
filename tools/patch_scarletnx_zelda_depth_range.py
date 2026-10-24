#!/usr/bin/env python3
"""Preserve the guest viewport depth range with the Vulkan extension, if present.

Apply after the stable-buffer pool; revert before it. Shaders/cache keys stay.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('    const char* dev_ext[24];', '    const char* dev_ext[32];'),
            ('    int has_divisor;      /* VK_EXT_vertex_attribute_divisor: instance divisors above 1 */',
             '    int depth_range_requested, has_depth_range, depth_range_enabled;\n'
             '    int has_divisor;      /* VK_EXT_vertex_attribute_divisor: instance divisors above 1 */'),
            ('void snx_vb_pool_report(u64 window);',
             'void snx_vb_pool_report(u64 window);\nvoid snx_depth_range_init(void);\nvoid snx_depth_range_report(u64 window);'),
        ],
        'src/nx/gpu/vk/device.c': [
            ('    int has_budget = 0;',
             '    int has_budget = 0;\n'
             '    const char* depth_range = getenv("SNX_VK_DEPTH_RANGE");\n'
             '    g_vk.depth_range_requested = depth_range && !strcmp(depth_range, "1");\n'
             '    g_vk.has_depth_range = g_vk.depth_range_enabled = 0;'),
            ('            if (!strcmp(e[i].extensionName, VK_EXT_MEMORY_BUDGET_EXTENSION_NAME)) has_budget = 1;',
             '            if (!strcmp(e[i].extensionName, VK_EXT_MEMORY_BUDGET_EXTENSION_NAME)) has_budget = 1;\n'
             '            if (!strcmp(e[i].extensionName, VK_EXT_DEPTH_RANGE_UNRESTRICTED_EXTENSION_NAME))\n'
             '                g_vk.has_depth_range = 1;'),
            ('    if (has_budget) ext[next++] = VK_EXT_MEMORY_BUDGET_EXTENSION_NAME;',
             '    if (has_budget) ext[next++] = VK_EXT_MEMORY_BUDGET_EXTENSION_NAME;\n'
             '    g_vk.depth_range_enabled = g_vk.depth_range_requested && g_vk.has_depth_range;\n'
             '    if (g_vk.depth_range_enabled) ext[next++] = VK_EXT_DEPTH_RANGE_UNRESTRICTED_EXTENSION_NAME;'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('VkViewport vk_render_viewport(const u32* r) {',
             '#include "nx/gpu/vk/snx_depth_range.h"\n\nVkViewport vk_render_viewport(const u32* r) {'),
            ('    vp.minDepth = zn < 0 ? 0 : zn > 1 ? 1 : zn;\n    vp.maxDepth = zf < 0 ? 0 : zf > 1 ? 1 : zf;',
             '    snx_depth_range_set(&vp, zn, zf);'),
            ('    VkViewport vp = vk_render_viewport(r);',
             '    VkViewport vp = vk_render_viewport(r);\n    snx_depth_range_note(r, &vp);'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_vb_pool_on();', '    snx_vb_pool_on();\n    snx_depth_range_init();'),
            ('snx_vb_pool_report(window); }', 'snx_vb_pool_report(window); snx_depth_range_report(window); }'),
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
            before, after = (new, old) if revert else (old, new)
            if text.count(before) != 1:
                raise ValueError('Unknown viewport-depth source; no changes: ' + name)
            text = text.replace(before, after, 1)
        updates[path] = text
    header = root / 'src/nx/gpu/vk/snx_depth_range.h'
    data = (HERE / 'zelda-perf/depth_range.h').read_text()
    if header.exists() and header.read_text() != data:
        raise ValueError('Unknown viewport-depth header')
    for path, text in updates.items():
        if path.read_text() != text:
            path.write_text(text)
    if revert:
        header.unlink(missing_ok=True)
    elif not header.exists():
        header.write_text(data)
    print('Zelda Vulkan viewport depth range:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
