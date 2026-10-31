#!/usr/bin/env python3
"""Opt-in backport: conditional EXIT does not discard reaching unconditional definitions.

The old translator treats every EXIT as a control-flow boundary. Lanes not taking
a conditional EXIT fall through. Keep predicated definitions conservative.
"""
import argparse
from pathlib import Path

OLD = """    int pred_written = 0, crossed = 0;
    /* where index's basic block starts:"""
NEW = """    int pred_written = 0, crossed = 0, conditional_exit_seen = 0;
    /* where index's basic block starts:"""
OLD_FLOW = """        if (j < block_start || op->id == O_BRA || op->id == O_BRX || op->id == O_CAL || op->id == O_RET ||
            op->id == O_SYNC || op->id == O_BRK || op->id == O_CONT || op->id == O_EXIT || op->id == O_KIL)
            crossed = 1;"""
NEW_FLOW = """        /* A conditional EXIT terminates only participating lanes; survivors fall through.
           Predicated definitions still require the conservative cross-flow checks below. */
        if (op->id == O_EXIT && !flow_always(insn[j])) conditional_exit_seen = 1;
        if (j < block_start || op->id == O_BRA || op->id == O_BRX || op->id == O_CAL || op->id == O_RET ||
            op->id == O_SYNC || op->id == O_BRK || op->id == O_CONT ||
            (op->id == O_EXIT && flow_always(insn[j])) || op->id == O_KIL)
            crossed = 1;"""
OLD_PRED = """        if (B(insn[j], 16, 4) != 7 && (crossed || B(insn[j], 16, 4) != guard || pred_written)) return -1;"""
NEW_PRED = """        if (B(insn[j], 16, 4) != 7 &&
            (crossed || conditional_exit_seen || B(insn[j], 16, 4) != guard || pred_written)) return -1;"""
PAIRS = [(OLD, NEW), (OLD_FLOW, NEW_FLOW), (OLD_PRED, NEW_PRED)]

def apply(root: Path, revert: bool = False):
    path = root / "src/nx/gpu/shader/spirv_translate.c"
    data = path.read_text()
    pairs = [(b, a) for a, b in PAIRS] if revert else PAIRS
    if all(data.count(b) == 1 and data.count(a) == 0 for a, b in pairs):
        return
    if revert and all(data.count(a) == 0 and data.count(b) == 1 for a, b in pairs):
        return
    if not all(data.count(a) == 1 and data.count(b) == 0 for a, b in pairs):
        raise ValueError("Unknown translator or partial patch; no source modified")
    for a, b in pairs:
        data = data.replace(a, b, 1)
    path.write_text(data)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--revert", action="store_true")
    a = p.parse_args()
    apply(a.source, a.revert)
