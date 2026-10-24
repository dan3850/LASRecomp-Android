#!/usr/bin/env python3
"""Adapt proven uniform prefixes to Vulkan without rewriting cached SPIR-V.

Apply after clear-load telemetry; restore before it. Analyze newly translated
and persisted modules identically. Unknown pointer use retains the old extent.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('    u64 qh, qh_a;\n    struct VkSh* next;\n} VkSh;',
             '    u64 qh, qh_a;\n    u32 snx_ub_extent[18]; /* transient proof; never serialized */\n'
             '    struct VkSh* next;\n} VkSh;\n'
             'int snx_ub_extent_on(void);\nu32 snx_ub_extent_len(const VkSh* s, u32 bank, u32 len);\n'
             'void snx_ub_extent_report(u64 window);'),
        ],
        'src/nx/gpu/vk/pipeline.c': [
            ('#include "nx/gpu/vk/pipeline_file.h"',
             '#include "nx/gpu/vk/pipeline_file.h"\n#include "nx/gpu/vk/snx_ub_extent.h"'),
            ('        if (spv) {\n            VkShaderModuleCreateInfo mi = {',
             '        if (spv) {\n'
             '            snx_ub_extent_shader(spv, nw, s);\n'
             '            VkShaderModuleCreateInfo mi = {'),
            ('    s->mod = vk_module_spv(spv, r->nspv);',
             '    snx_ub_extent_shader(spv, r->nspv, s);\n'
             '    s->mod = vk_module_spv(spv, r->nspv);'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('        if (sz > g_vk.props.limits.maxUniformBufferRange) sz = g_vk.props.limits.maxUniformBufferRange;\n'
             '        VkBuffer b;',
             '        if (sz > g_vk.props.limits.maxUniformBufferRange) sz = g_vk.props.limits.maxUniformBufferRange;\n'
             '        sz = snx_ub_extent_len(s, (u32)i, sz);\n'
             '        VkBuffer b;'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_clear_load_on();', '    snx_clear_load_on();\n    snx_ub_extent_on();'),
            ('snx_clear_load_report(window); }',
             'snx_clear_load_report(window); snx_ub_extent_report(window); }'),
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
                raise ValueError('unknown pinned uniform-extent source; no files changed: ' + name)
            text = text.replace(source, target, 1)
        updates[path] = text
    header = root / 'src/nx/gpu/vk/snx_ub_extent.h'
    data = (HERE / 'zelda-perf/ub_extent.h').read_text()
    if header.exists() and header.read_text() != data:
        raise ValueError('generated uniform-extent header differs; no files changed: ' + str(header))
    updates[header] = None if revert else data
    for path, text in updates.items():
        if text is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_text() != text:
            path.write_text(text)
    print('Zelda proven uniform extents:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
