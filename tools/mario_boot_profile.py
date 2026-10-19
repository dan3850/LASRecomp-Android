#!/usr/bin/env python3
"""Bind an Android boot runtime to an existing private Mario test library.

Reads the linked build report and the user's NSOs; never regenerates game code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from nso import Nso

START_ABIS = (('_ZN2nn4init5StartEmmPFvvES2_S2_', 5),
              ('_ZN2nn4init5StartEmmPFvvES2_', 4))


def sdk_startup(nso, base):
    lo, size = nso.text
    functions = {name: value for name, info, section, value, _ in nso.syms
                 if section and (info & 15) == 2 and lo <= value < lo + size and value % 4 == 0}
    for name, arguments in START_ABIS:
        if name in functions:
            return {'symbol': name, 'address': hex(base + functions[name]), 'arguments': arguments}
    candidates = sorted(n for n, *_ in nso.syms if n.startswith('_ZN2nn4init5Start'))
    raise ValueError('sdk: no supported nn::init::Start export (4 or 5 arguments); candidates: ' +
                     (', '.join(candidates) if candidates else 'none'))


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_changed(path, text):
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return
    tmp = path.with_name(path.name + '.partial')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def prepare(report_path, exefs, output, *, host_test=False):
    report_path, exefs, output = Path(report_path), Path(exefs), Path(output)
    if (exefs / 'exefs').is_dir():
        exefs /= 'exefs'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('profile') != 'mario' or report.get('status') != 'linked_requires_runtime':
        raise ValueError('a linked Mario full-recompiler build report is required')
    if report.get('additional_nso_modules'):
        raise ValueError('additional modules need loader support first: ' + ', '.join(report['additional_nso_modules']))
    identity = report.get('library_id', '')
    if not re.fullmatch(r'mario-full:[0-9a-f]{24}', identity):
        raise ValueError('invalid Mario library identity')
    library = report_path.parent / 'libmario_test.so'
    with library.open('rb') as stream:
        header = stream.read(64)
    if len(header) < 64 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 16)[0] != 3:
        raise ValueError('not an ELF64 shared library')
    machine = struct.unpack_from('<H', header, 18)[0]
    if machine != 183 and not (host_test and machine == 62):
        raise ValueError('the APK requires an Android ARM64 library')
    if report.get('link', {}).get('sha256') != sha256(library):
        raise ValueError('library differs from its completed build report; do not mix builds')
    builds, images, bases = {}, {}, {}
    for name in ('main', 'sdk'):
        path = exefs / name
        expected = report['inputs'][name]
        if sha256(path) != expected['sha256']:
            raise ValueError(f'{name}: executable differs from the one used to compile this library')
        nso = Nso(path)
        if nso.build_id != expected['build_id']:
            raise ValueError(f'{name}: Build ID mismatch')
        module = report['modules'][name]
        if not module.get('complete') or module.get('functions', 0) < 1:
            raise ValueError(f'{name}: incomplete function table')
        base = int(report['bases'][name], 0)
        if int(module['base'], 0) != base or module['build_id'] != nso.build_id:
            raise ValueError(f'{name}: generation and loader metadata disagree')
        with path.open('rb') as stream:
            stream.seek(0x40)
            builds[name] = stream.read(32)
        images[name], bases[name] = nso.size, base
        if name == 'sdk':
            startup = sdk_startup(nso, base)
    if bases['main'] != 0x7000000000 or bases['sdk'] < bases['main'] + images['main'] or \
            bases['sdk'] + images['sdk'] > 0x7080000000 or bases['sdk'] & 0xFFFF:
        raise ValueError('invalid or overlapping Mario module bases')
    output.mkdir(parents=True, exist_ok=True)
    lines = ['#pragma once', '#define LASRECOMP_MARIO_TEST 1',
             '#define GAMELIB_ID ' + json.dumps(identity),
             '#define GAMELIB_ENTRY "mario_test_tables"',
             '#define GAMELIB_ANDROID_NAME "libmario_test.so"']
    for name in ('main', 'sdk'):
        lines += [f'#define {name.upper()}_BASE 0x{bases[name]:x}ull',
                  '#define MARIO_' + name.upper() + '_BUILD_ID_BYTES {' +
                  ','.join(f'0x{b:02x}' for b in builds[name]) + '}']
    write_changed(output / 'mario_profile_config.h', '\n'.join(lines) + '\n')
    metadata = {'profile': 'mario', 'library_id': identity, 'boot_tested': False,
                'build_ids': {n: b.hex() for n, b in builds.items()},
                'bases': {n: hex(b) for n, b in bases.items()},
                'library_sha256': report['link']['sha256'], 'startup': startup}
    write_changed(output / 'mario_boot_profile.json', json.dumps(metadata, indent=2, sort_keys=True) + '\n')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    metadata = prepare(args.report, args.game, args.output)
    print('Perfil Mario vinculado a biblioteca existente: ' + metadata['library_id'])
    print('MAIN=' + metadata['bases']['main'] + ' SDK=' + metadata['bases']['sdk'])
    print('START=' + metadata['startup']['symbol'] + ' ENDERECO=' + metadata['startup']['address'] +
          ' ARGUMENTOS=' + str(metadata['startup']['arguments']))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit('ERRO: ' + str(error))
