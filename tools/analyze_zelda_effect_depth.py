#!/usr/bin/env python3
"""Compare captured attachment/sampled depth planes without extracting a ZIP.

The current attachment is not a proven producer of the sampled copy. Pixel
differences alone do not prove a bug: draws between copies may change depth.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
import zipfile

_spec = importlib.util.spec_from_file_location('effect_shadow_depth', Path(__file__).with_name('analyze_zelda_shadows.py'))
DEPTH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DEPTH)


def analyze_pair(meta, raw, output_prefix=None):
    if meta.get('schema') != 'SNX_EFFECT_DEPTH_PAIR_V1' or meta.get('byte_order') != 'little':
        raise ValueError('Unknown effect depth format')
    w, h, fmt = (meta.get(x) for x in ('width', 'height', 'format'))
    if type(w) is not int or type(h) is not int or not 0 < w <= 8192 or not 0 < h <= 8192:
        raise ValueError('Invalid effect shape')
    if type(fmt) is not int or fmt not in (125, 126, 129, 130):
        raise ValueError('Unsupported effect depth format')
    plane_bytes = w * h * 4
    size = plane_bytes * 2
    if size > DEPTH.CAP_BYTES or meta.get('bytes') != size or len(raw) != size:
        raise ValueError('Truncated or inconsistent effect depth bytes')
    planes = meta.get('planes')
    if not isinstance(planes, list) or len(planes) != 2:
        raise ValueError('Expected two effect planes')
    result = {'schema': 'SNX_EFFECT_DEPTH_ANALYSIS_V1', 'capture': meta.get('capture'), 'frame': meta.get('frame'),
              'format': fmt, 'width': w, 'height': h, 'consumer': meta.get('consumer'),
              'producer_relationship': 'unproven', 'planes': []}
    for i, role in enumerate(('attachment', 'sampled')):
        p = planes[i]
        if not isinstance(p, dict) or p.get('role') != role or p.get('offset') != plane_bytes * i or p.get('bytes') != plane_bytes:
            raise ValueError('Invalid effect plane layout')
        single = {'schema': 'SNX_SHADOW_DEPTH_V1', 'byte_order': 'little', 'mip': 0, 'image_width': w,
                  'image_height': h, 'layers': 1, 'format': fmt, 'bytes': plane_bytes, 'surface': p.get('surface')}
        prefix = None if output_prefix is None else str(output_prefix) + '-' + role
        facts = DEPTH.analyze_pair(single, memoryview(raw)[i * plane_bytes:(i + 1) * plane_bytes], prefix)
        result['planes'].append({'role': role, 'surface': p.get('surface'), 'wgen': p.get('wgen'), **facts['layers'][0]})
    code, mask = DEPTH.FORMATS[fmt]
    n, equal, total, maximum = 0, 0, 0.0, 0.0
    a = struct.iter_unpack('<' + code, memoryview(raw)[:plane_bytes])
    b = struct.iter_unpack('<' + code, memoryview(raw)[plane_bytes:])
    for (av,), (bv,) in zip(a, b):
        if mask:
            av, bv = (av & mask) / mask, (bv & mask) / mask
        if not math.isfinite(av) or not math.isfinite(bv): continue
        delta = abs(av - bv)
        equal += av == bv
        n += 1
        total += delta
        maximum = max(maximum, delta)
    result['comparison'] = {'finite_pairs': n, 'equal': equal, 'different': n - equal,
                            'nonfinite_pairs': w * h - n, 'max_abs': maximum if n else None,
                            'mean_abs': total / n if n else None, 'is_bug': None}
    return result


def analyze_archive(path, output=None):
    with zipfile.ZipFile(path) as z:
        items = [x for x in z.infolist() if re.fullmatch(r'effects/[0-9a-f]{16}/effect-[1-3]\.json', x.filename)]
        if not items or len(items) > 3 or len({Path(x.filename).parent for x in items}) != 1:
            raise ValueError('Expected 1..3 pairs from one effect session')
        if len({x.filename for x in z.infolist()}) != len(z.infolist()):
            raise ValueError('Duplicate archive entry')
        if output is not None: Path(output).mkdir(parents=True, exist_ok=True)
        results = []
        for item in sorted(items, key=lambda x: x.filename):
            if not 0 < item.file_size <= 16384: raise ValueError('Invalid effect metadata size')
            meta = json.loads(z.read(item))
            raw_name = item.filename[:-5] + '.depth'
            try: raw_item = z.getinfo(raw_name)
            except KeyError as e: raise ValueError('Missing effect depth') from e
            if not 0 < raw_item.file_size <= DEPTH.CAP_BYTES: raise ValueError('Invalid effect depth size')
            prefix = None if output is None else Path(output) / Path(item.filename).stem
            results.append(analyze_pair(meta, z.read(raw_item), prefix))
        return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--previews', type=Path)
    args = parser.parse_args()
    try: print(json.dumps(analyze_archive(args.archive, args.previews), indent=2))
    except (ValueError, OSError, zipfile.BadZipFile) as e: parser.exit(2, str(e) + '\n')
