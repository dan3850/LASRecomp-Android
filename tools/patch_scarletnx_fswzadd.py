#!/usr/bin/env python3
"""Experimental, reversible ScarletNX FSWZADD quad-mask 0xD7 patch.

The game's log identifies the exact instruction 50f8000d70... with swizzle
mask 0xD7 in rejected fragment shaders. The pinned ScarletNX translator
supports only masks 0x99/0x66/0xA5/0x5A, so those shaders are omitted.

0xD7 encodes swizzle selectors [3,1,1,3] for the quad's four lanes.
Ryujinx's FSWZADD swizzle LUT (x=[1,-1,1,0], y=[1,1,-1,1])
maps the middle lanes to y-x and the outer lanes to y. For this first
experiment, support ONLY 0xD7, using subgroup lane ID & 3. The four
older derivative cases remain byte-for-byte untouched. Other masks are
still rejected; this patch is not a general FSWZADD implementation.

Only edits local ScarletNX source matching pinned 34853ee; never edits
compiled AOT output or the working Mario repository branch. --revert
restores the exact source patterns without deleting unrelated patches.
"""
from pathlib import Path
import argparse

REPLACES = (
    (
        """        case O_FSWZADD: {
            u32 quad = B(w, 28, 8);
            return !B(w, 47, 1) && (quad == 0x99 || quad == 0x66 || quad == 0xa5 || quad == 0x5a);
        }""",
        """        case O_FSWZADD: {
            u32 quad = B(w, 28, 8);
            /* Castlevania shader: 0xD7 = swizzle [3,1,1,3] in quad order. */
            return !B(w, 47, 1) &&
                   (quad == 0x99 || quad == 0x66 || quad == 0xa5 || quad == 0x5a || quad == 0xd7);
        }""",
    ),
    (
        """        if (op->id == O_VOTE || op->id == O_SHFL) needs_subgroup = 1;""",
        """        if (op->id == O_VOTE || op->id == O_SHFL ||
            (op->id == O_FSWZADD && B(insn[i], 28, 8) == 0xd7))
            needs_subgroup = 1;""",
    ),
    (
        """            if (quad == 0x99 || quad == 0x66 || quad == 0xa5 || quad == 0x5a) {
                result = spv_emit_derivative(&c->emit, c->f32_type, rhs, quad == 0xa5 || quad == 0x5a);
                if (quad == 0x66 || quad == 0x5a) result = spv_emit_fnegate(&c->emit, c->f32_type, result);
            } else
                result = spv_emit_fadd(&c->emit, c->f32_type, lhs, rhs);""",
        """            if (quad == 0xd7) {
                /* 0xD7 selects [3,1,1,3]: lane 0/3 -> y; lane 1/2 -> y-x.
                   The device's subgroup lane order is used as a first
                   experiment. Some fragment layouts may not align quads
                   with subgroup lanes; confirm visually on the device. */
                u32 lane = spv_emit_load(&c->emit, c->u32_type, c->subgroup_lane_input);
                lane = spv_emit_bitwise_and_u32(&c->emit, c->u32_type, lane,
                                                spv_emit_constant_u32(&c->emit, c->u32_type, 3));
                u32 is_one = spv_emit_i_equal(&c->emit, c->bool_type, lane,
                                               spv_emit_constant_u32(&c->emit, c->u32_type, 1));
                u32 is_two = spv_emit_i_equal(&c->emit, c->bool_type, lane,
                                               spv_emit_constant_u32(&c->emit, c->u32_type, 2));
                u32 middle = spv_emit_select(&c->emit, c->bool_type, is_one, c->true_value, is_two);
                u32 subtract = spv_emit_fadd(&c->emit, c->f32_type, rhs,
                                              spv_emit_fnegate(&c->emit, c->f32_type, lhs));
                result = spv_emit_select(&c->emit, c->f32_type, middle, subtract, rhs);
            } else if (quad == 0x99 || quad == 0x66 || quad == 0xa5 || quad == 0x5a) {
                result = spv_emit_derivative(&c->emit, c->f32_type, rhs, quad == 0xa5 || quad == 0x5a);
                if (quad == 0x66 || quad == 0x5a) result = spv_emit_fnegate(&c->emit, c->f32_type, result);
            } else
                result = spv_emit_fadd(&c->emit, c->f32_type, lhs, rhs);""",
    ),
)


def apply(text: str, revert: bool = False) -> str:
    # Atomic validation: never half-patch a source when an upstream pattern
    # has changed or another developer already changed part of this code.
    pairs = [(b, a) if revert else (a, b) for a, b in REPLACES]
    states = []
    for old, new in pairs:
        old_count = text.count(old)
        new_count = text.count(new)
        if old_count == 1 and new_count == 0:
            states.append("change")
        elif old_count == 0 and new_count == 1:
            states.append("already")
        else:
            raise ValueError("ScarletNX differs from pinned shader translator; refuse patch")
    if len(set(states)) != 1:
        raise ValueError("Partially applied shader patch; do not modify mixed source")
    if states[0] == "already":
        return text
    result = text
    for old, new in pairs:
        result = result.replace(old, new, 1)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path, help="Root of the pinned ScarletNX source tree")
    ap.add_argument("--revert", action="store_true", help="Restore upstream shader translator")
    args = ap.parse_args()
    target = args.source / "src/nx/gpu/shader/spirv_translate.c"
    original = target.read_text()
    modified = apply(original, args.revert)
    if modified != original:
        target.write_text(modified)
    print(("Reverted" if args.revert else "Applied") +
          " experimental Castlevania FSWZADD 0xD7 patch:", target)


if __name__ == "__main__":
    main()
