#!/usr/bin/env python3
"""Mandatory Castlevania cold JIT sessions in ABI 2 builds; preserve existing cache files.

The source remains pinned. This selects the JIT service's supported NULL
cache_path, keeping normal on-demand compilation and all AOT entries intact.
It also skips warm hints so every reopen follows the cold, on-demand path.
"""
import argparse
from pathlib import Path

MARKER = 'SNX_JIT_COLD_START_V1'
RELATIVE = 'src/nx/runtime/guest_jit.c'
REPLACES = (
    ('    config.cache_path = g_jit_cache;',
     '''    /* SNX_JIT_COLD_START_V1: isolate persisted CPU code from the ABI 2 reopen test.
       NULL disables both cache_open and cache_append in the JIT service.
       Keep the old file for diagnosis; never reuse it for this title. */
    int cold_jit = !strcmp(g_exename, "0100BA4026E94000");
    config.cache_path = cold_jit ? NULL : g_jit_cache;
    if (cold_jit)
        LOG("jit: SNX_JIT_COLD_START_V1: persistent units and warm hints bypassed; files preserved\\n");'''),
    ('    hints = hints_copy(&hint_count);',
     '''    hint_count = 0;
    hints = cold_jit ? NULL : hints_copy(&hint_count);'''),
)


def transform(text, revert=False):
    # Work in memory; refuse changed upstream anchors before writing anything.
    for old, new in reversed(REPLACES) if revert else REPLACES:
        source, target = (new, old) if revert else (old, new)
        if text.count(target) == 1 and source not in text:
            continue
        if text.count(source) != 1:
            raise ValueError('pinned JIT source changed: ' + source[:75])
        text = text.replace(source, target, 1)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('scarletnx', type=Path)
    ap.add_argument('--revert', action='store_true')
    args = ap.parse_args()
    path = args.scarletnx / RELATIVE
    before = path.read_text()
    after = transform(before, args.revert)
    if after != before:
        path.write_text(after)
    print('Castlevania ABI 2 JIT cold-session guard:', 'RESTORED' if args.revert else 'INSTALLED')


if __name__ == '__main__':
    main()
