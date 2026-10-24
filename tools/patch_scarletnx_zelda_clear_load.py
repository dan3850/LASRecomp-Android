#!/usr/bin/env python3
"""Fold eligible immediate full clears into a new Vulkan pass's load action.

Apply after uniform telemetry; restore before it. No pending-clear queue,
attachment discard, pass reordering or changes to original write bookkeeping.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
BEGIN_OLD = 'static int render_begin(Surf** rt, Surf* zt, u32 n, int zt_ro, int srgb_write, u32 fb) {'
BEGIN_NEW = 'static int render_begin_load(Surf** rt, Surf* zt, u32 n, int zt_ro, int srgb_write, u32 fb, SnxClearLoad* load) {'
LOAD_OLD = '''    VkRenderingInfo ri = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO,
                          .renderArea = {{0, 0}, ext},'''
LOAD_NEW = '''    if (load) {
        if (load->color_slot >= 0) {
            ca[load->color_slot].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
            ca[load->color_slot].clearValue = load->color;
        }
        if (load->ds) {
            za.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
            za.clearValue.depthStencil = load->depth;
        }
    }
    VkRenderingInfo ri = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO,
                          .renderArea = {{0, 0}, ext},'''
CLEAR_OLD = '''    int zt_undefined = zt && zt->layout == VK_IMAGE_LAYOUT_UNDEFINED;
    if (!render_begin(rt, zt, n, 0, r[0x56E] & 1, 0)) return;'''
CLEAR_NEW = '''    int zt_undefined = zt && zt->layout == VK_IMAGE_LAYOUT_UNDEFINED;
    SnxClearLoad load;
    int load_ready = snx_clear_load_prepare(ch, v, rt, zt, n, dz, &load);
    if (!render_begin_load(rt, zt, n, 0, r[0x56E] & 1, 0, load_ready ? &load : NULL)) return;
    if (load_ready && !load.applied) snx_clear_counts[SNX_CL_CONTINUED]++;'''
COMMAND_OLD = '''        pred_begin(vk_cmd(), ch->render_pred);
        rec_CmdClearAttachments(vk_cmd(), na, at, 1, &rect);
        pred_end(vk_cmd(), ch->render_pred);'''
COMMAND_NEW = '''        if (load.applied) snx_clear_load_used(&load, g_rp.ext);
        else {
            pred_begin(vk_cmd(), ch->render_pred);
            rec_CmdClearAttachments(vk_cmd(), na, at, 1, &rect);
            pred_end(vk_cmd(), ch->render_pred);
        }'''


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_uniform_report(u64 window);',
             'void snx_uniform_report(u64 window);\nint snx_clear_load_on(void);\nvoid snx_clear_load_report(u64 window);'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('#include "nx/gpu/vk/pending_pages.h"',
             '#include "nx/gpu/vk/pending_pages.h"\n#include "nx/gpu/vk/snx_clear_load.h"'),
            (BEGIN_OLD, BEGIN_NEW), (LOAD_OLD, LOAD_NEW),
            ('    rec_CmdBeginRendering(cb, &ri);\n    memcpy(g_rp.rt, rt, sizeof g_rp.rt);',
             '    rec_CmdBeginRendering(cb, &ri);\n    if (load) load->applied = 1;\n    memcpy(g_rp.rt, rt, sizeof g_rp.rt);'),
            ('static void target_written(Surf* s) {',
             BEGIN_OLD + '\n    return render_begin_load(rt, zt, n, zt_ro, srgb_write, fb, NULL);\n}\n'
             'static void target_written(Surf* s) {'),
            (CLEAR_OLD, CLEAR_NEW), (COMMAND_OLD, COMMAND_NEW),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_uniform_on();', '    snx_uniform_on();\n    snx_clear_load_on();'),
            ('snx_uniform_report(window); }', 'snx_uniform_report(window); snx_clear_load_report(window); }'),
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
                raise ValueError('unknown pinned clear-load source; no files changed: ' + name)
            text = text.replace(source, target, 1)
        updates[path] = text
    header = root / 'src/nx/gpu/vk/snx_clear_load.h'
    data = (HERE / 'zelda-perf/clear_load.h').read_text()
    if header.exists() and header.read_text() != data:
        raise ValueError('generated clear-load header differs; no files changed: ' + str(header))
    updates[header] = None if revert else data
    for path, text in updates.items():
        if text is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_text() != text:
            path.write_text(text)
    print('Zelda immediate full clears as load actions:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
