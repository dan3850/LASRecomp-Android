#!/usr/bin/env python3
"""Allow qualified packed D24/S8 targets to feed existing GPU memory copies.

Apply after effect-depth evidence, restore first. Runtime opt-in; original
shaders/caches/AOT stay. The internal compute conversion packs exact bits.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


PACK_GLSL = '''    if (mode == TC_PACK_Z24S8 || mode == TC_PACK_S8Z24) {
        uint row = gl_GlobalInvocationID.y;
        if (row >= rows || gl_GlobalInvocationID.z != 0u) return;
        uint d = src[in_bias + row * in_pitch + u] & 0xFFFFFFu;
        uint s = (src[st_bias + row * st_pitch + u / 4u] >> (8u * (u & 3u))) & 255u;
        dst[out_bias + row * out_pitch + u] = mode == TC_PACK_Z24S8 ? (d << 8) | s : d | (s << 24);
        return;
    }
'''

PACK_C = '''/* Separate Vulkan depth/stencil planes to the guest's packed texels.
 * Input and output descriptor ranges must be disjoint, even in one buffer. */
int vk_tc_d24_pack_supported(void) {
    u64 n = texconv_spv_size / 4;
    u32 found = 0;
    if (texconv_spv_size % 4 || n < 5 || texconv_spv[0] != 0x07230203u) return 0;
    /* Unique mode constants must be in the actual generated module. A stale
     * Ninja/CMake shader must never enable a C-only conversion path. */
    for (u64 i = 5; i < n;) {
        u32 words = texconv_spv[i] >> 16, op = texconv_spv[i] & 0xffff;
        if (!words || words > n - i) return 0;
        if (op == 43 && words == 4) {
            found |= texconv_spv[i + 3] == TC_PACK_Z24S8 ? 1u : 0u;
            found |= texconv_spv[i + 3] == TC_PACK_S8Z24 ? 2u : 0u;
        }
        i += words;
    }
    return found == 3;
}

int vk_tc_pack_d24(VkCommandBuffer cb, u32 z24s8, u32 w, u32 h, VkBuffer in, u64 depth_at, u32 depth_pitch,
                    u64 stencil_at, u32 stencil_pitch, VkBuffer out, u64 out_at, u32 out_pitch) {
    u64 align = storage_align(), in_off = depth_at & ~(align - 1), out_off = out_at & ~(align - 1);
    u64 depth_end = depth_at + (u64)depth_pitch * h, stencil_end = stencil_at + (u64)stencil_pitch * h;
    u64 in_end = depth_end > stencil_end ? depth_end : stencil_end;
    u64 out_end = out_at + (u64)out_pitch * h;
    if (!w || !h || stencil_at < depth_end || depth_pitch < (u64)w * 4 || stencil_pitch < w ||
        out_pitch < (u64)w * 4 || ((depth_at | depth_pitch | stencil_at | stencil_pitch | out_at | out_pitch) & 3))
        return 0;
    if (in == out && out_off < in_end && in_off < out_end) return 0;
    TcParams p = {.mode = z24s8 ? TC_PACK_Z24S8 : TC_PACK_S8Z24, .units = w, .rows = h,
                  .in_pitch = depth_pitch / 4, .out_pitch = out_pitch / 4, .st_pitch = stencil_pitch / 4,
                  .in_bias = (u32)((depth_at - in_off) / 4), .st_bias = (u32)((stencil_at - in_off) / 4),
                  .out_bias = (u32)((out_at - out_off) / 4)};
    return tc_dispatch(cb, &p, (w + 63) / 64, h, 1, in, in_off, in_end - in_off,
                       out, out_off, out_at + (u64)out_pitch * h - out_off);
}

'''


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_effect_depth_init(void);',
             'void snx_effect_depth_init(void);\nvoid snx_d24_pack_init(void);\nvoid snx_d24_pack_report(u64 window);'),
            ('int vk_tc_converts(const VkFmt* f);',
             'int vk_tc_converts(const VkFmt* f);\n'
             'int vk_tc_d24_pack_supported(void);\n'
             'int vk_tc_pack_d24(VkCommandBuffer cb, u32 z24s8, u32 w, u32 h, VkBuffer in, u64 depth_at, u32 depth_pitch,\n'
             '                    u64 stencil_at, u32 stencil_pitch, VkBuffer out, u64 out_at, u32 out_pitch);'),
        ],
        'src/nx/gpu/vk/surface.c': [
            ('static u64 flush_bytes(const Surf* s) {',
             '#include "nx/gpu/vk/snx_d24_pack.h"\n\nstatic u64 flush_bytes(const Surf* s) {'),
            ('static u32 rt_pending_over(u64 gva, u64 size, Surf** local, u32 nlocal, Surf*** out) {',
             'static u32 rt_pending_over(u64 gva, u64 size, Surf** local, u32 nlocal, Surf*** out, int d24_overlay) {'),
            ('s->gva + rt_bytes(s) <= gva || !flush_bytes(s)) continue;',
             's->gva + rt_bytes(s) <= gva ||\n'
             '                !(flush_bytes(s) || (d24_overlay && snx_d24_pack_pending(s, gva, size)))) continue;'),
            ('rt_pending_over(s->gva, size, local, 16, &list);',
             'rt_pending_over(s->gva, size, local, 16, &list, 0);'),
            ('count = rt_pending_over(gva, size, local, 16, &list);\n    for',
             'count = rt_pending_over(gva, size, local, 16, &list, 1);\n    for'),
            ('count = rt_pending_over(gva, size, local, 16, &list);\n        for',
             'count = rt_pending_over(gva, size, local, 16, &list, 0);\n        for'),
            ('if (flush_record(vk_cmd(), s, buf, at + (s->gva - gva))) {',
             'if (snx_d24_pack_eligible(s) ? snx_d24_pack_record(vk_cmd(), s, buf, at + (s->gva - gva)) :\n'
             '                flush_record(vk_cmd(), s, buf, at + (s->gva - gva))) {'),
        ],
        'src/nx/gpu/vk/texconv.c': [
            ('int vk_tc_nv12_uv(VkCommandBuffer cb,', PACK_C + 'int vk_tc_nv12_uv(VkCommandBuffer cb,'),
        ],
        'src/nx/gpu/texture/texconv_modes.glsl': [
            ('#define TC_BLIT 22u', '#define TC_BLIT 22u\n'
             '/* Vulkan X8_D24 depth + R8 stencil planes to guest packed words, one texel/invocation. */\n'
             '#define TC_PACK_Z24S8 0x534e0014u /* ZT 0x14: depth high 24, stencil low 8 */\n'
             '#define TC_PACK_S8Z24 0x534e0016u /* ZT 0x16: stencil high 8, depth low 24 */'),
        ],
        'src/nx/gpu/texture/texconv.glsl': [
            ('    if (mode == TC_BLIT) {', PACK_GLSL + '    if (mode == TC_BLIT) {'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('    snx_effect_depth_init();', '    snx_effect_depth_init();\n    snx_d24_pack_init();'),
            ('snx_lighting_report(window); }', 'snx_lighting_report(window); snx_d24_pack_report(window); }'),
        ],
    }


def apply(root, revert=False):
    changes = {}
    for name, pairs in replacements().items():
        path = root / name; text = path.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1: continue
            if revert and new not in text and text.count(old) == 1: continue
            before, after = (new, old) if revert else (old, new)
            if text.count(before) != 1:
                raise ValueError('Unknown D24 source; no changes: ' + name)
            text = text.replace(before, after, 1)
        changes[path] = text
    header = root / 'src/nx/gpu/vk/snx_d24_pack.h'
    data = (HERE / 'zelda-perf/d24_pack.h').read_text()
    if header.exists() and header.read_text() != data:
        raise ValueError('Unknown D24 header; no changes')
    for path, text in changes.items():
        if path.read_text() != text: path.write_text(text)
    if revert: header.unlink(missing_ok=True)
    elif not header.exists(): header.write_text(data)
    print('Zelda exact packed-depth memory copies:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args(); apply(args.source, args.revert)
