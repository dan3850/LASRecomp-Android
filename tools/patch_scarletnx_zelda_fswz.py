#!/usr/bin/env python3
"""Reversible operand-exact FSWZADD repair for the Zelda audit runtime.

The captured shadow readers use masks A5/99 after SHFL.BFLY. ScarletNX's
derivative substitution ignores SrcA and has the opposite sign for that
pair. Preserve the four currently accepted masks, both actual operands and
the Maxwell per-lane sign table. Do not broaden instruction acceptance.

Apply after perf_opt and before compilation (after the optional Castlevania
D7 patch). Restore before either patch. Old SPIR-V must not be prewarmed:
use a separate directory, preserving every existing shader/driver cache.
"""
import argparse
from pathlib import Path

SHADER_PAIRS = (
    (
        '        if (op->id == O_FSWZADD) {\n            if (a < 255) used[a] = 1;',
        '        if (op->id == O_FSWZADD) {\n'
        '            needs_subgroup = 1; /* FSWZADD uses the same lane numbering as SHFL. */\n'
        '            if (a < 255) used[a] = 1;',
    ),
    (
        '''                result = spv_emit_derivative(&c->emit, c->f32_type, rhs, quad == 0xa5 || quad == 0x5a);
                if (quad == 0x66 || quad == 0x5a) result = spv_emit_fnegate(&c->emit, c->f32_type, result);''',
        '''                /* Maxwell selectors: 0 x+y, 1 y-x, 2 x-y, 3 y.
                   99/66 alternate selectors 1/2 across x; A5/5A across y.
                   SrcA may be unrelated to SrcB. A derivative is not this operation. */
                u32 lane = spv_emit_load(&c->emit, c->u32_type, c->subgroup_lane_input);
                u32 axis = spv_emit_constant_u32(&c->emit, c->u32_type, quad == 0xa5 || quad == 0x5a ? 2 : 1);
                lane = spv_emit_bitwise_and_u32(&c->emit, c->u32_type, lane, axis);
                u32 low = spv_emit_i_equal(&c->emit, c->bool_type, lane, c->zero);
                u32 y_minus_x = spv_emit_fadd(&c->emit, c->f32_type, rhs,
                                               spv_emit_fnegate(&c->emit, c->f32_type, lhs));
                u32 x_minus_y = spv_emit_fadd(&c->emit, c->f32_type, lhs,
                                               spv_emit_fnegate(&c->emit, c->f32_type, rhs));
                int forward = quad == 0x99 || quad == 0xa5;
                result = spv_emit_select(&c->emit, c->f32_type, low,
                                          forward ? y_minus_x : x_minus_y,
                                          forward ? x_minus_y : y_minus_x);''',
    ),
)
CACHE_PAIRS = (
    (
        '    snprintf(g_cache_dir, sizeof g_cache_dir, "%sshader_cache/fps-audit-v1", g_cachedir);\n'
        '    plat_mkdir(g_cache_dir);',
        '    snprintf(g_cache_dir, sizeof g_cache_dir, "%sshader_cache/fps-audit-fswz-v1", g_cachedir);\n'
        '    plat_mkdir(g_cache_dir);\n'
        '    LOG("vulkan: SNX_FSWZADD_V1 operand-exact masks=99,66,a5,5a; isolated shader/driver cache\\n");',
    ),
)


def transform(text, pairs, revert=False):
    states = []
    for old, new in pairs:
        a, b = (new, old) if revert else (old, new)
        counts = text.count(a), text.count(b)
        if counts == (1, 0): states.append('change')
        elif counts == (0, 1): states.append('already')
        else: raise ValueError('Unknown pinned FSWZADD/cache source; no files changed')
    if len(set(states)) != 1:
        raise ValueError('Partial FSWZADD patch; no files changed')
    if states[0] == 'already': return text
    for old, new in pairs:
        a, b = (new, old) if revert else (old, new)
        text = text.replace(a, b, 1)
    return text


def transform_shader(text, revert=False):
    return transform(text, SHADER_PAIRS, revert)


def apply(root, revert=False):
    updates = {}
    changed = []
    for name, pairs in (('src/nx/gpu/shader/spirv_translate.c', SHADER_PAIRS),
                        ('src/nx/gpu/vk/pipeline.c', CACHE_PAIRS)):
        path = root / name
        original = path.read_text()
        updates[path] = transform(original, pairs, revert)
        changed.append(updates[path] != original)
    if len(set(changed)) != 1:
        raise ValueError('Partial FSWZADD/cache patch; no files changed')
    for path, text in updates.items():
        if path.read_text() != text: path.write_text(text)
    print('Zelda operand-exact FSWZADD / isolated shader cache:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
