#!/usr/bin/env python3
"""Inspect a Zelda-sombras.zip without dependencies or extracting game data.

Print per-layer depth facts; optionally write nearest-sampled PGM previews.
Constant depth is evidence, not proof that a particular game pass is wrong.
"""
import argparse
import json
import math
from pathlib import Path
import re
import struct
import zipfile

CAP_BYTES = 64 * 1024 * 1024
# A Vulkan DEPTH-aspect copy is planar, even for a depth/stencil image.
# D24 copies as X8_D24_UNORM_PACK32: the high eight bits are undefined.
FORMATS = {124: ('H', 65535), 128: ('H', 65535), 125: ('I', 16777215),
           129: ('I', 16777215), 126: ('f', None), 130: ('f', None)}


def producer_state(meta):
    draw = meta.get('last_recorded_depth_draw', {})
    if draw.get('same_generation') != 1:
        return {'known': False}
    registers = draw.get('registers', {})
    def word(key):
        value = registers.get(key)
        return int(value, 16) if isinstance(value, str) and re.fullmatch('[0-9a-fA-F]{8}', value) else None
    def floating(key):
        value = word(key)
        if value is None:
            return None
        result = struct.unpack('<f', struct.pack('<I', value))[0]
        return result if math.isfinite(result) else None
    depth_mode, origin = word('35f'), word('4eb')
    return {'known': True, 'predicated': bool(draw.get('predicated')),
            'depth_mode': None if depth_mode is None else 'zero_to_one' if depth_mode & 1 else 'minus_one_to_one',
            'origin_lower_left': None if origin is None else bool(origin & 1),
            'window_flip_y': None if origin is None else bool(origin & 16),
            'depth_test': word('4b3'), 'depth_write': word('4ba'), 'depth_func': word('4c3'),
            'bias_factor_register': floating('55b'), 'bias_units_register': floating('56f'),
            'bias_clamp_register': floating('61f'),
            'viewport_registers': [floating(f'{x:03x}') for x in range(0x280, 0x286)]}


def analyze_pair(meta, raw, output_prefix=None):
    if meta.get('schema') != 'SNX_SHADOW_DEPTH_V1' or meta.get('byte_order') != 'little' or meta.get('mip') != 0:
        raise ValueError('Unknown depth capture format')
    w, h, layers = (meta.get(x) for x in ('image_width', 'image_height', 'layers'))
    if any(type(x) is not int or x <= 0 for x in (w, h, layers)) or w > 8192 or h > 8192 or layers > 16:
        raise ValueError('Invalid image shape')
    if type(meta.get('format')) is not int or meta['format'] not in FORMATS:
        raise ValueError('Unsupported depth format')
    code, mask = FORMATS[meta['format']]
    element = struct.Struct('<' + code)
    size = w * h * layers * element.size
    if size > CAP_BYTES or len(raw) != size or meta.get('bytes') != size:
        raise ValueError('Truncated or inconsistent depth bytes')
    result = {'schema': 'SNX_SHADOW_ANALYSIS_V1', 'capture': meta.get('capture'), 'frame': meta.get('frame'),
              'surface': meta.get('surface'), 'format': meta['format'], 'width': w, 'height': h,
              'producer_state': producer_state(meta), 'layers': []}
    for layer in range(layers):
        data = memoryview(raw)[layer * w * h * element.size:(layer + 1) * w * h * element.size]
        low, high, total, finite, zero, one, outside = math.inf, -math.inf, 0.0, 0, 0, 0, 0
        histogram = [0] * 16
        def depth(value):
            return (value & mask) / mask if mask else value
        for (value,) in struct.iter_unpack('<' + code, data):
            value = depth(value)
            if not math.isfinite(value):
                continue
            low, high = min(low, value), max(high, value)
            total += value
            finite += 1
            zero += value == 0
            one += value == 1
            outside += not 0 <= value <= 1
            if 0 <= value <= 1:
                histogram[min(15, int(value * 16))] += 1
        facts = {'layer': layer, 'pixels': w * h, 'nonfinite': w * h - finite, 'outside_0_1': outside,
                 'min': low if finite else None, 'max': high if finite else None,
                 'mean': total / finite if finite else None, 'zero': zero, 'one': one,
                 'constant_finite': bool(finite and low == high), 'histogram_0_1': histogram}
        if output_prefix is not None:
            pw, ph = min(512, w), min(512, h)
            linear, stretched = bytearray(pw * ph), bytearray(pw * ph)
            for py in range(ph):
                for px in range(pw):
                    offset = ((py * h // ph) * w + px * w // pw) * element.size
                    value = depth(element.unpack_from(data, offset)[0])
                    if math.isfinite(value):
                        linear[py * pw + px] = round(max(0, min(1, value)) * 255)
                        scaled = (value - low) / (high - low) if high > low else 0
                        stretched[py * pw + px] = round(max(0, min(1, scaled)) * 255)
            for name, pixels in [('raw', linear), ('range', stretched)]:
                path = Path(str(output_prefix) + f'-layer-{layer}-{name}.pgm')
                path.write_bytes(f'P5\n{pw} {ph}\n255\n'.encode() + pixels)
            facts['preview'] = 'first image row preserved; range preview rescales finite min/max per layer'
        result['layers'].append(facts)
    return result


def analyze_archive(path, output=None):
    results = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        metas = sorted(n for n in names if re.fullmatch(r'shadows/[0-9a-f]{16}/shadow-[1-3]\.json', n))
        if not metas or len(metas) > 3 or len({n.split('/')[1] for n in metas}) != 1:
            raise ValueError('Expected one session with 1..3 complete captures')
        for name in metas:
            depth_name = name.removesuffix('.json') + '.depth'
            if names.count(name) != 1 or names.count(depth_name) != 1:
                raise ValueError('Missing or duplicate capture entry')
            if z.getinfo(name).file_size > 16384 or z.getinfo(depth_name).file_size > CAP_BYTES:
                raise ValueError('Capture exceeds size limit')
            meta = json.loads(z.read(name))
            prefix = None
            if output is not None:
                output.mkdir(parents=True, exist_ok=True)
                prefix = output / Path(name).stem
            results.append(analyze_pair(meta, z.read(depth_name), prefix))
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', type=Path)
    parser.add_argument('--out', type=Path, help='optional directory for PGM previews and summary.json')
    args = parser.parse_args()
    report = analyze_archive(args.zip, args.out)
    rendered = json.dumps(report, indent=2, allow_nan=False)
    if args.out:
        (args.out / 'summary.json').write_text(rendered + '\n')
    print(rendered)
