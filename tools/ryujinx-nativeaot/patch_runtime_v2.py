#!/usr/bin/env python3
"""Install ABI 2 into a fresh, pinned ScarletNX checkout, never into old binaries."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('    VkCbReads cbr;\n    ShaderInfo si;',
             '    VkCbReads cbr;\n    void* ryu_facts; /* live GPU facts used during NativeAOT translation */\n    int ryujinx; /* ABI 2 support UBO at SNX_VKB_RS */\n    ShaderInfo si;'),
        ],
        'src/nx/gpu/vk/pipeline.c': [
            ('static VkCbReader g_rec_read;',
             '#include "nx/gpu/vk/snx_ryu_runtime_v2.h"\nstatic VkCbReader g_rec_read;'),
            ('if (same && vk_cb_reads_hold(&s->cbr, sh_cb_read)) return s;',
             'if (same && vk_cb_reads_hold(&s->cbr, sh_cb_read) && snx_rn_facts_hold(s)) return s;'),
            ('q->qh_a == qh_a && vk_cb_reads_hold(&q->cbr, sh_cb_read))',
             'q->qh_a == qh_a && vk_cb_reads_hold(&q->cbr, sh_cb_read) && snx_rn_facts_hold(q))'),
            ('        u32* spv = vk_translate_spirv(code, 0x10000, stage, &s->si, &nw, sh_cb_read, &s->cbr);',
             '        u32* spv = snx_rn_try_v2(code, mlen, stage, s, &nw);\n'
             '        if (!spv) spv = vk_translate_spirv(code, 0x10000, stage, &s->si, &nw, sh_cb_read, &s->cbr);'),
            ('    if (getenv("SNX_SHADER_CORPUS")) {',
             '    if (snx_rn_enabled()) {\n'
             '        snx_rn_init_v2(); /* fail before rendering if a stale .so was packaged */\n'
             '        LOG("vulkan: RYUJINX_NATIVE_V2: persistent shader prewarm bypassed; files preserved\\n");\n'
             '        return;\n    }\n    if (getenv("SNX_SHADER_CORPUS")) {'),
        ],
        'src/nx/gpu/vk/render.c': [
            ('    if (st->bindless && st->bl2) {\n'
             '        u64 c2 = c2i < 18 ? ch->cbind[stage][c2i] : 0;\n'
             '        if (c2) h |= gmem_r32(c2 + st->bl2_off * 4);\n    }',
             '    if (st->bindless && st->bl2) {\n'
             '        u64 c2 = c2i < 18 ? ch->cbind[stage][c2i] : 0;\n'
             '        u32 sampler = st->bl2 == 3 ? st->bl2_off : c2 ? gmem_r32(c2 + st->bl2_off * 4) : 0;\n'
             '        h |= st->bl2 >= 2 ? sampler << 20 : sampler;\n    }'),
            ('static VkDescriptorSet stage_set(GpuChannel* ch,',
             '#include "nx/gpu/vk/snx_ryu_support_v2.h"\nstatic VkDescriptorSet stage_set(GpuChannel* ch,'),
            ('    if (stage == 4 && frame_consts(&cb, &co))',
             '    float ryu_scales[65];\n    for (unsigned j = 0; j < 65; j++) ryu_scales[j] = 1.0f;\n'
             '    ryu_scales[0] = g_vk_scale;\n'
             '    if (stage == 4 && !s->ryujinx && frame_consts(&cb, &co))'),
            ('        Surf* t = x->t;\n        if (st->flags & 2)',
             '        Surf* t = x->t;\n'
             '        if (s->ryujinx && t && t->w) ryu_scales[i + 1] = (float)t->sw / t->w;\n'
             '        if (st->flags & 2)'),
            ('    return desc_set_cached(layout, &d);',
             '    if (s->ryujinx) {\n'
             '        if (!snx_ryu_support(ryu_scales, r[0x4C4], &cb, &co)) return VK_NULL_HANDLE;\n'
             '        dw_buffer(&d, set, SNX_VKB_RS, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, cb, co, SNX_RYU_SUPPORT_SIZE);\n'
             '    }\n    return desc_set_cached(layout, &d);'),
        ],
    }


def apply(root, identity, revision):
    updated = {}
    for name, pairs in replacements().items():
        path = root / name
        text = path.read_text()
        for old, new in pairs:
            if text.count(new) == 1:
                continue
            if text.count(old) != 1:
                raise ValueError(f'pinned source changed: {name}: {old[:75]!r}')
            text = text.replace(old, new, 1)
        updated[path] = text
    # No file is touched until ALL pinned-source anchors have passed.
    for path, text in updated.items():
        if path.read_text() != text:
            path.write_text(text)
    destination = root / 'src/nx/gpu/vk'
    for source, target in [('scarlet_runtime_v2.h', 'snx_ryu_runtime_v2.h'),
                           ('scarlet_support_v2.h', 'snx_ryu_support_v2.h')]:
        (destination / target).write_bytes((HERE / source).read_bytes())
    (destination / 'snx_ryu_expected.h').write_text(
        '#define SNX_RYU_EXPECTED_IDENTITY ' + json.dumps(identity) + '\n' +
        '#define SNX_RUNTIME_REVISION ' + json.dumps(revision) + '\n')
    print('ABI 2 installed:', identity, 'runtime:', revision)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('scarletnx', type=Path)
    ap.add_argument('--identity', type=Path, required=True)
    ap.add_argument('--revision', required=True)
    a = ap.parse_args()
    apply(a.scarletnx, json.loads(a.identity.read_text())['source_identity'], a.revision)


if __name__ == '__main__':
    main()
