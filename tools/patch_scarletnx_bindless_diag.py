#!/usr/bin/env python3
"""Reversible, pinned-source instrumentation for ScarletNX bindless failures.

Diagnostic ONLY: preserves the existing shader accept/reject behavior.
"""
import argparse
from pathlib import Path

OLD = 'if (bindless && !handle_count) return direct_reject(si, "untracked texture handle");'
NEW = '''if (bindless && !handle_count) {
                /* Diagnostic only: keep rejection, expose failed handle provenance. */
                char detail[160];
                u32 handle_reg = (op->id == O_TXD_B || op->id == O_TXQ_B) ? a : b;
                int def = direct_reaching_def(insn, n, i, handle_reg);
                const Op* producer = def >= 0 ? decode(insn[def]) : NULL;
                snprintf(detail, sizeof detail,
                         "untracked texture handle op=%d pc=%u reg=%u def=%d producer=%d",
                         (int)op->id, i, handle_reg, def, producer ? (int)producer->id : -1);
                return direct_reject(si, detail);
            }'''

def transform(source: str, revert: bool = False) -> str:
    before, after = (NEW, OLD) if revert else (OLD, NEW)
    old_count, new_count = source.count(before), source.count(after)
    if old_count == 0 and new_count == 6:
        return source
    if old_count != 6 or new_count:
        raise ValueError(f"Unexpected ScarletNX version or partial patch: old={old_count}, new={new_count}")
    return source.replace(before, after)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    target = args.source_root / "src/nx/gpu/shader/spirv_translate.c"
    source = target.read_text()
    result = transform(source, args.revert)
    if result != source:
        target.write_text(result)
    print(("Reverted" if args.revert else "Applied") + " bindless handle diagnostic: " + str(target))

if __name__ == "__main__":
    main()
