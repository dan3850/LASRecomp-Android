#!/usr/bin/env python3
"""Analyze exported ScarletNX logs; no game files, third-party modules or adb.

Accepts prefixed log lines and combines raw frame intervals across COMPLETE
windows. Android displayed FPS and game simulation FPS cannot be inferred.
"""
import argparse
import json
import math
import re
from pathlib import Path

PATTERN = re.compile(r'(SNX_(?:PERF_META|PERF|FRAMES|STREAM|COST|VK|RYU_CACHE|HASH_SPAN(?:_META)?|TRANSFER(?:_META)?|UNIFORM(?:_META)?|CLEAR_LOAD(?:_META)?|UB_EXTENT(?:_META)?|BIND_REUSE(?:_META)?|VB_POOL(?:_META)?|DEPTH_RANGE(?:_META|_STATE)?|WW(?:_META|_EVENT)|SHADOW_CAPTURE|GFX(?:_META|_PASS|_BIND|_LIMIT)?)_V1) (\{.*)')


def percentile(values, pct):
    return sorted(values)[max(0, math.ceil(len(values) * pct / 100) - 1)] if values else None


def analyze(text, skip_seconds=10, duration_seconds=None, session=None):
    if 'SNX_PERF_EXPORT_TRUNCATED' in text:
        raise ValueError('performance export truncated; export a shorter session')
    if '=== SNX PERF BEGIN ===' in text:
        text = text.split('=== SNX PERF BEGIN ===', 1)[1]
        if '=== SNX PERF END ===' not in text:
            raise ValueError('performance export incomplete')
        text = text.split('=== SNX PERF END ===', 1)[0]
    sessions = []
    current = None
    for line in text.splitlines():
        m = PATTERN.search(line)
        if not m:
            continue
        try:
            row = json.loads(m[2])
        except json.JSONDecodeError as e:
            raise ValueError('truncated/invalid telemetry; export the full log: ' + str(e)) from e
        if m[1] == 'SNX_PERF_META_V1':
            current = {'meta': row, 'rows': []}
            sessions.append(current)
        elif current is not None:
            current['rows'].append((m[1], row))
    if not sessions:
        raise ValueError('No SNX_PERF_META_V1. Install the audit APK, select LEVE, play and export its full log.')
    if session is None and len(sessions) != 1:
        raise ValueError(f'{len(sessions)} sessions found; select --session 1..{len(sessions)} explicitly.')
    index = (session or 1) - 1
    if index < 0 or index >= len(sessions):
        raise ValueError('session out of range')
    selected = sessions[index]
    if any(k == 'SNX_SHADOW_CAPTURE_V1' and r.get('status') in ('armed', 'queued', 'saved', 'save_failed')
           for k, r in selected['rows']):
        raise ValueError('Shadow depth capture was armed: visual diagnostics are not an FPS comparison. Disable capture and restart.')
    cache = [r for k, r in selected['rows'] if k == 'SNX_RYU_CACHE_V1']
    hash_meta = [r for k, r in selected['rows'] if k == 'SNX_HASH_SPAN_META_V1']
    transfer_meta = [r for k, r in selected['rows'] if k == 'SNX_TRANSFER_META_V1']
    uniform_meta = [r for k, r in selected['rows'] if k == 'SNX_UNIFORM_META_V1']
    clear_meta = [r for k, r in selected['rows'] if k == 'SNX_CLEAR_LOAD_META_V1']
    extent_meta = [r for k, r in selected['rows'] if k == 'SNX_UB_EXTENT_META_V1']
    binding_meta = [r for k, r in selected['rows'] if k == 'SNX_BIND_REUSE_META_V1']
    vb_meta = [r for k, r in selected['rows'] if k == 'SNX_VB_POOL_META_V1']
    depth_meta = [r for k, r in selected['rows'] if k == 'SNX_DEPTH_RANGE_META_V1']
    all_windows = {r['window']: r for k, r in selected['rows'] if k == 'SNX_PERF_V1'}
    # Include only windows wholly inside the requested time range. No mix of
    # startup/warmup with gameplay, no partial-window FPS extrapolation.
    windows = {w: r for w, r in all_windows.items()
               if r['elapsed_s'] - r['duration_ms'] / 1000 >= skip_seconds - 0.002
               and (duration_seconds is None or r['elapsed_s'] <= skip_seconds + duration_seconds)}
    valid = {}
    for w, r in windows.items():
        if depth_meta:
            depth_rows = [x for k, x in selected['rows'] if k == 'SNX_DEPTH_RANGE_V1' and x['window'] == w]
            if len(depth_rows) != 1:
                continue
            if depth_rows[0]['enabled'] != depth_meta[-1]['enabled']:
                raise ValueError('viewport-depth mode changed within session')
        if vb_meta:
            vb_rows = [x for k, x in selected['rows'] if k == 'SNX_VB_POOL_V1' and x['window'] == w]
            if len(vb_rows) != 1:
                continue
            if vb_rows[0]['enabled'] != vb_meta[-1]['enabled']:
                raise ValueError('persistent buffer mode changed within session')
        streams = {x['stream']: x for k, x in selected['rows'] if k == 'SNX_STREAM_V1' and x['window'] == w}
        costs = {x['metric']: x for k, x in selected['rows'] if k == 'SNX_COST_V1' and x['window'] == w}
        vk = [x for k, x in selected['rows'] if k == 'SNX_VK_V1' and x['window'] == w]
        if len(streams) != 3 or len(costs) != 16 or len(vk) != 1:
            continue  # crash/export during a flush: do not count that partial window
        if hash_meta:
            spans = [x for k, x in selected['rows'] if k == 'SNX_HASH_SPAN_V1' and x['window'] == w]
            if len(spans) != 1:
                continue
            if spans[0]['enabled'] != hash_meta[-1]['enabled']:
                raise ValueError('hash-span mode changed within a session')
        if transfer_meta:
            transfers = [x for k, x in selected['rows'] if k == 'SNX_TRANSFER_V1' and x['window'] == w]
            if len(transfers) != 1:
                continue
            if transfers[0]['enabled'] != transfer_meta[-1]['enabled']:
                raise ValueError('transfer mode changed within a session')
        if uniform_meta:
            uniforms = [x for k, x in selected['rows'] if k == 'SNX_UNIFORM_V1' and x['window'] == w]
            if len(uniforms) != 1:
                continue
            if uniforms[0]['enabled'] != uniform_meta[-1]['enabled']:
                raise ValueError('uniform mode changed within a session')
        if clear_meta:
            clears = [x for k, x in selected['rows'] if k == 'SNX_CLEAR_LOAD_V1' and x['window'] == w]
            if len(clears) != 1:
                continue
            if clears[0]['enabled'] != clear_meta[-1]['enabled']:
                raise ValueError('clear-load mode changed within a session')
        if extent_meta:
            extents = [x for k, x in selected['rows'] if k == 'SNX_UB_EXTENT_V1' and x['window'] == w]
            if len(extents) != 1:
                continue
            if extents[0]['enabled'] != extent_meta[-1]['enabled']:
                raise ValueError('uniform-extent mode changed within a session')
        if binding_meta:
            bindings = [x for k, x in selected['rows'] if k == 'SNX_BIND_REUSE_V1' and x['window'] == w]
            if len(bindings) != 1:
                continue
            if bindings[0]['enabled'] != binding_meta[-1]['enabled']:
                raise ValueError('binding-reuse mode changed within a session')
        for name, s in streams.items():
            n = sum(len(x['us']) for k, x in selected['rows']
                    if k == 'SNX_FRAMES_V1' and x['window'] == w and x['stream'] == name)
            if n != s['samples']:
                raise ValueError(f'missing or duplicated frame chunks in window {w}, stream {name}')
            if s['lost']:
                raise ValueError(f'frame sample capacity exceeded in window {w}; percentiles would be biased')
        valid[w] = r
    if not valid:
        raise ValueError('No complete windows in this range. Play longer or reduce --skip-seconds.')
    seconds = sum(r['duration_ms'] for r in valid.values()) / 1000
    result = {'session': index + 1, 'metadata': selected['meta'], 'seconds': round(seconds, 3),
              'windows': len(valid), 'streams': {}, 'costs': {}, 'vulkan': {},
              'displayed_fps': None, 'simulation_fps': None}
    if cache:
        result['metadata']['effective_cache'] = cache[-1]
    if hash_meta:
        result['metadata']['hash_span'] = hash_meta[-1]
    if transfer_meta:
        result['metadata']['transfers'] = transfer_meta[-1]
    if uniform_meta:
        result['metadata']['uniforms'] = uniform_meta[-1]
    if clear_meta:
        result['metadata']['clear_load'] = clear_meta[-1]
    if extent_meta:
        result['metadata']['uniform_extent'] = extent_meta[-1]
    if binding_meta:
        result['metadata']['binding_reuse'] = binding_meta[-1]
    if vb_meta:
        result['metadata']['persistent_buffers'] = vb_meta[-1]
    if depth_meta:
        result['metadata']['depth_range'] = depth_meta[-1]
        result['depth_range_states'] = [r for k, r in selected['rows'] if k == 'SNX_DEPTH_RANGE_STATE_V1']
    ww_meta = [r for k, r in selected['rows'] if k == 'SNX_WW_META_V1']
    if ww_meta:
        result['metadata']['write_watch'] = ww_meta[-1]
        result['write_watch_events'] = [r for k, r in selected['rows'] if k == 'SNX_WW_EVENT_V1']
    graphics_meta = [r for k, r in selected['rows'] if k == 'SNX_GFX_META_V1']
    if graphics_meta:
        result['metadata']['graphics_diagnostics'] = graphics_meta[-1]
    for name in ('guest_queue', 'render', 'present_enqueue'):
        frames = sum(r['frames'] for k, r in selected['rows']
                     if k == 'SNX_STREAM_V1' and r['window'] in valid and r['stream'] == name)
        us = [v for k, r in selected['rows'] if k == 'SNX_FRAMES_V1'
              and r['window'] in valid and r['stream'] == name for v in r['us']]
        result['streams'][name] = {
            'frames': frames, 'fps': round(frames / seconds, 3), 'intervals': len(us),
            **{f'p{p}_ms': round(percentile(us, p) / 1000, 3) if us else None for p in (50, 95, 99)},
            'max_ms': round(max(us) / 1000, 3) if us else None,
            'over_16_67ms': sum(v > 16667 for v in us),
            'over_33_33ms': sum(v > 33333 for v in us), 'over_50ms': sum(v > 50000 for v in us)}
    for k, r in selected['rows']:
        if r.get('window') not in valid:
            continue
        if k == 'SNX_COST_V1':
            c = result['costs'].setdefault(r['metric'], {'calls': 0, 'ms': 0})
            c['calls'] += r['calls']
            c['ms'] = round(c['ms'] + r['ms'], 3)
        if k == 'SNX_VK_V1':
            for name, value in r.items():
                if name == 'window':
                    continue
                if name.startswith('prewarm_'):  # gauges/cumulative, never sum them
                    result['vulkan'][name] = value
                else:
                    result['vulkan'][name] = result['vulkan'].get(name, 0) + value
        if k == 'SNX_GFX_V1':
            graphics = result.setdefault('graphics', {})
            for name, value in r.items():
                if name != 'window':
                    graphics[name] = graphics.get(name, 0) + value
        if k == 'SNX_HASH_SPAN_V1':
            spans = result.setdefault('hash_span', {})
            for name, value in r.items():
                if name not in ('window', 'enabled'):
                    spans[name] = spans.get(name, 0) + value
        if k == 'SNX_TRANSFER_V1':
            transfers = result.setdefault('transfers', {})
            for name, value in r.items():
                if name in ('pool_bytes', 'pool_entries'):
                    transfers[name] = value  # live gauges, never sum across windows
                elif name not in ('window', 'enabled'):
                    transfers[name] = transfers.get(name, 0) + value
        if k == 'SNX_UNIFORM_V1':
            uniforms = result.setdefault('uniforms', {})
            for name, value in r.items():
                if name not in ('window', 'enabled'):
                    uniforms[name] = uniforms.get(name, 0) + value
        if k == 'SNX_CLEAR_LOAD_V1':
            clears = result.setdefault('clear_load', {})
            for name, value in r.items():
                if name not in ('window', 'enabled'):
                    clears[name] = clears.get(name, 0) + value
        if k == 'SNX_UB_EXTENT_V1':
            extents = result.setdefault('uniform_extent', {})
            for name, value in r.items():
                if name not in ('window', 'enabled'):
                    extents[name] = extents.get(name, 0) + value
        if k == 'SNX_BIND_REUSE_V1':
            bindings = result.setdefault('binding_reuse', {})
            for name, value in r.items():
                if name not in ('window', 'enabled'):
                    bindings[name] = bindings.get(name, 0) + value
        if k == 'SNX_VB_POOL_V1':
            buffers = result.setdefault('persistent_buffers', {})
            for name, value in r.items():
                if name in ('pool_entries', 'pool_bytes'):
                    buffers[name] = value
                elif name not in ('window', 'enabled'):
                    buffers[name] = buffers.get(name, 0) + value
        if k == 'SNX_DEPTH_RANGE_V1':
            depth = result.setdefault('depth_range', {})
            for name, value in r.items():
                if name not in ('window', 'enabled'):
                    depth[name] = depth.get(name, 0) + value
    return result


def markdown(report, label):
    lines = [f'### {label}', f"Measured: {report['seconds']:.3f} s, {report['windows']} complete windows.", '',
             '| Stream | FPS | p50 ms | p95 ms | p99 ms | >33.33 ms |',
             '|---|---:|---:|---:|---:|---:|']
    for name, s in report['streams'].items():
        lines.append(f"| {name} | {s['fps']} | {s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} | {s['over_33_33ms']} |")
    lines += ['', 'Thread wall times below overlap; do not add them to infer frame time. '
              'For hash_bytes, the count is bytes rather than calls.', '',
              '| Cost | Calls | ms |', '|---|---:|---:|']
    for name, c in report['costs'].items():
        lines.append(f"| {name} | {c['calls']} | {c['ms']} |")
    lines += ['', 'Vulkan counters: `' + json.dumps(report['vulkan'], sort_keys=True) + '`', '',
              'Metadata: `' + json.dumps(report['metadata'], sort_keys=True) + '`', '',
              'present_enqueue counts successful/suboptimal vkQueuePresentKHR calls. '
              'Physical display FPS and game simulation FPS are unavailable.']
    if 'graphics' in report:
        lines += ['', 'Detailed graphics setup counters: `' + json.dumps(report['graphics'], sort_keys=True) + '`',
                  'Null bindings may be intentional; indexed entries count descriptor preparation, not actual shader samples.']
    if 'hash_span' in report:
        lines += ['', 'Range-qualified hash reads: `' + json.dumps(report['hash_span'], sort_keys=True) + '`',
                  'direct_bytes still undergo the full original hash; they avoid staging copies, not content checks.']
    if 'transfers' in report:
        lines += ['', 'Persistent Vulkan transfers: `' + json.dumps(report['transfers'], sort_keys=True) + '`',
                  'Pool hits avoid new allocations; row-call and destination-byte savings count work removed, not milliseconds or FPS.']
    if 'uniforms' in report:
        lines += ['', 'Strict graphics uniform snapshots: `' + json.dumps(report['uniforms'], sort_keys=True) + '`',
                  'Reused snapshots passed strict checks; promotion_bypasses counts decisions, not guaranteed successful baseline copies or FPS.']
    if 'clear_load' in report:
        lines += ['', 'Immediate full clears as load actions: `' + json.dumps(report['clear_load'], sort_keys=True) + '`',
                  'Folded commands retain their clear effects; pixel counts are initialized areas, not measured bandwidth savings or FPS.']
    if 'uniform_extent' in report:
        lines += ['', 'Proven uniform prefixes: `' + json.dumps(report['uniform_extent'], sort_keys=True) + '`',
                  'Byte totals are requested binding ranges, not measured uploads, bandwidth savings or FPS. All shader instructions remain unchanged.']
    if 'binding_reuse' in report:
        lines += ['', 'Exact reuse of resolved bindings: `' + json.dumps(report['binding_reuse'], sort_keys=True) + '`',
                  'Fast hits bypass descriptor hash lookups; resource checks still run. Mix-call counts are CPU work counts, not GPU time or FPS.']
    if 'persistent_buffers' in report:
        lines += ['', 'Persistent vertex/index/storage buffers: `' + json.dumps(report['persistent_buffers'], sort_keys=True) + '`',
                  'Pool hits avoid new allocations; all original data copies and content checks remain. Counts are not measured FPS gains.']
    if 'write_watch_events' in report:
        lines += ['', 'Passive write-watch initialization/errors: `' + json.dumps(report['write_watch_events'], sort_keys=True) + '`',
                  'Build UAPI, syscall/API, registration, pagemap and scan failures are distinct. Policy and fallback checks are unchanged.']
    if 'depth_range' in report:
        lines += ['', 'Vulkan viewport depth: `' + json.dumps(report['depth_range'], sort_keys=True) + '`',
                  'Unrestricted ranges require the enabled device extension. These counts do not establish restored shadows.']
    return '\n'.join(lines)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=Path)
    p.add_argument('--compare', type=Path)
    p.add_argument('--skip-seconds', type=float, default=10)
    p.add_argument('--seconds', type=float)
    p.add_argument('--session', type=int)
    p.add_argument('--json', action='store_true')
    a = p.parse_args()
    try:
        reports = [analyze(path.read_text(errors='replace'), a.skip_seconds, a.seconds, a.session)
                   for path in ([a.log, a.compare] if a.compare else [a.log])]
        if a.json:
            print(json.dumps(reports if a.compare else reports[0], indent=2))
        else:
            print('\n\n'.join(markdown(r, name) for r, name in zip(reports, ['A', 'B'])))
    except (OSError, ValueError) as e:
        p.error(str(e))
