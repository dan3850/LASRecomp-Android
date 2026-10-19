#!/usr/bin/env python3
"""Generate whole Mario main/sdk modules with gen.py, then optionally link them.

The private library needs runtime integration; linking is not an Android boot.
No game files, generated C or objects should be committed or uploaded.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

from nso import Nso

ROOT = Path(__file__).resolve().parents[1]
MAIN_BASE = 0x7000000000
SDK_BASE = 0x7004000000
HLE_BASE = 0x7080000000
GENERATOR_FILES = ('tools/gen.py', 'tools/lifter.py', 'tools/analyze.py',
                   'tools/nso.py', 'tools/simd_c.py')
HEADERS = ('runtime/cpu.h', 'runtime/simd.h', 'runtime/simd_fp.h', 'runtime/gamelib.h')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    text = json.dumps(value, indent=2, sort_keys=True) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return
    tmp = path.with_name(path.name + '.partial')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def input_info(path):
    nso = Nso(path)
    if not nso.build_id:
        raise ValueError(f'{path}: missing Build ID')
    return {'build_id': nso.build_id, 'sha256': file_hash(path),
            'image_bytes': nso.size, 'dependencies': nso.needed}


def module_bases(main_size, sdk_size):
    # Mario's image need not fit in Zelda's fixed 64 MiB main window.
    sdk = max(SDK_BASE, (MAIN_BASE + main_size + 0xFFFF) & ~0xFFFF)
    if sdk + sdk_size > HLE_BASE:
        raise ValueError('main/sdk overlap the runtime HLE address range')
    return {'main': MAIN_BASE, 'sdk': sdk}


def generate(name, source, folder, info, base, simd, generator_id):
    folder.mkdir(parents=True, exist_ok=True)
    spec = {'input': info, 'base': hex(base), 'simd': simd,
            'profile': 'mario', 'generator': generator_id}
    key = digest(spec)
    stamp_path, report_path = folder / 'generation-state.json', folder / 'generation.json'
    stamp, report = read_json(stamp_path), read_json(report_path)
    hashes = stamp.get('sources', {})
    reusable = (stamp.get('key') == key and report.get('complete') is True and
                report.get('functions', 0) > 0 and report.get('build_id') == info['build_id'] and
                set(hashes) == set(report.get('sources', [])) and bool(hashes) and
                stamp.get('report_sha256') == (file_hash(report_path) if report_path.is_file() else None))
    if reusable:
        reusable = all((folder / p).is_file() and file_hash(folder / p) == sha
                       for p, sha in hashes.items())
    if reusable:
        print(f'{name}: geracao completa reutilizada ({report["functions"]} funcoes)', flush=True)
    else:
        print(f'{name}: gerando modulo completo, Build ID {info["build_id"]}, base {base:#x}', flush=True)
        subprocess.run([sys.executable, str(ROOT / 'tools/gen.py'), name,
                        str(source), hex(base), str(folder), '--profile', 'mario',
                        '--expect-build-id', info['build_id'], '--no-stable60-menu',
                        '--simd', simd, '--report', str(report_path)], check=True)
        report = read_json(report_path)
        if not report.get('complete') or report.get('functions', 0) == 0:
            raise ValueError(f'{name}: incomplete generation; no library will be linked')
        if file_hash(source) != info['sha256']:
            raise ValueError(f'{name}: input changed during generation; run again')
        hashes = {p: file_hash(folder / p) for p in report['sources']}
        write_json(stamp_path, {'key': key, 'sources': hashes,
                               'report_sha256': file_hash(report_path)})
    print(f'{name}: {report["functions"]} funcoes; '
          f'{report["stats"].get("unsupported", 0)} instrucoes nao suportadas; '
          f'{report["stats"].get("trap_words", 0)} palavras com trap (inclui dados/padding)', flush=True)
    return report, [folder / p for p in report['sources']]


def nm_symbols(nm, library, mode):
    result = subprocess.run([nm, '-D', mode, str(library)], check=True,
                            capture_output=True, text=True)
    return sorted({line.split()[-1].split('@')[0]
                   for line in result.stdout.splitlines() if line.split()})


def compile_library(out, sources, identity, jobs, cc, nm, host_test, previous):
    target = platform.machine().lower()
    termux = target in ('aarch64', 'arm64') and os.environ.get('PREFIX') == '/data/data/com.termux/files/usr'
    if not termux and not host_test:
        raise ValueError('compile directly in ARM64 Termux; --host-test is only for development fixtures')
    compiler = shutil.which(cc)
    nm = shutil.which(nm or 'llvm-nm') or shutil.which('nm')
    if not compiler or not nm:
        raise ValueError('clang and llvm-nm (or nm) are required')
    version = subprocess.check_output([compiler, '--version'], text=True)
    headers = {p: file_hash(ROOT / p) for p in HEADERS}
    flags = ['-std=gnu11', '-O1', '-g0', '-fPIC', '-fno-strict-aliasing',
             '-fvisibility=hidden', '-Wno-unused-label', '-Wno-return-type',
             '-I' + str(ROOT / 'runtime')]
    all_sources = [*sources, ROOT / 'tools/mario_test_entry.c']

    def compile_one(source):
        relative = source.relative_to(out / 'generated') if source in sources else Path('mario_test_entry.c')
        obj = out / 'objects' / relative.with_suffix('.o')
        signature = obj.with_suffix('.json')
        source_flags = flags if source in sources else [*flags, '-DGAMELIB_ID=' + json.dumps(identity)]
        key = digest({'source': file_hash(source), 'headers': headers,
                      'compiler': compiler, 'version': version, 'flags': source_flags})
        if obj.is_file() and obj.stat().st_size > 0 and read_json(signature).get('key') == key:
            return obj, key, False
        obj.parent.mkdir(parents=True, exist_ok=True)
        tmp = obj.with_suffix('.o.partial')
        print(f'CC {relative}', flush=True)
        subprocess.run([compiler, *source_flags, '-c', str(source), '-o', str(tmp)], check=True)
        tmp.replace(obj)
        write_json(signature, {'key': key})
        return obj, key, True

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        objects = list(pool.map(compile_one, all_sources))
    link_flags = ['-shared', '-Wl,-z,max-page-size=16384', '-Wl,--build-id=sha1',
                  '-Wl,-soname,libmario_test.so']
    link_key = digest({'objects': [(str(o), k) for o, k, _ in objects],
                       'compiler': compiler, 'version': version, 'flags': link_flags})
    library = out / 'libmario_test.so'
    expected_machine = 183 if target in ('arm64', 'aarch64') else 62 if target == 'x86_64' else None
    if expected_machine is None:
        raise ValueError('unsupported build host')
    if (previous.get('key') == link_key and library.is_file() and
            previous.get('sha256') == file_hash(library)):
        linked = previous
    else:
        tmp = library.with_suffix('.so.partial')
        print(f'LD {library}', flush=True)
        subprocess.run([compiler, *link_flags, '-o', str(tmp),
                        *(str(o) for o, _, _ in objects), '-lm'], check=True)
        with tmp.open('rb') as stream:
            header = stream.read(64)
        if header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 18)[0] != expected_machine:
            raise ValueError('linked library has the wrong ELF architecture')
        defined = nm_symbols(nm, tmp, '--defined-only')
        undefined = nm_symbols(nm, tmp, '--undefined-only')
        if 'mario_test_tables' not in defined:
            raise ValueError('missing mario_test_tables export')
        missing_guest = [s for s in undefined if re.fullmatch(r'f_[0-9a-f]+', s)]
        if missing_guest:
            raise ValueError('unlinked guest functions: ' + ', '.join(missing_guest[:20]))
        # These are deliberately resolved by the future host runtime, not by fake stubs here.
        linked = {'key': link_key, 'sha256': file_hash(tmp), 'elf_machine': expected_machine,
                  'export': 'mario_test_tables', 'undefined_symbols': undefined,
                  'runtime_integration_required': True}
        tmp.replace(library)
    return linked, sum(built for _, _, built in objects), len(objects)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exefs', type=Path, help='local exefs directory, or its parent game directory')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/private-mario-full-test')
    parser.add_argument('--compile', action='store_true', help='also compile and link the private test library')
    parser.add_argument('--simd', choices=('asm', 'c'), default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--nm')
    parser.add_argument('--host-test', action='store_true', help='allow native Linux fixture builds outside Termux')
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 8:
        parser.error('--jobs must be 1..8')
    exefs = args.exefs.expanduser().resolve()
    if (exefs / 'exefs').is_dir():
        exefs /= 'exefs'
    out = args.output.expanduser().resolve()
    if out == exefs or out in exefs.parents or exefs in out.parents:
        parser.error('output must be separate from input files')
    if out == ROOT or (ROOT in out.parents and ROOT / 'build' not in out.parents):
        parser.error('inside the repository, output must be under build/ (gitignored)')
    for name in ('main', 'sdk'):
        if not (exefs / name).is_file():
            parser.error(f'missing {exefs / name}')
    if args.compile and not args.host_test and (
            platform.machine().lower() not in ('arm64', 'aarch64') or
            os.environ.get('PREFIX') != '/data/data/com.termux/files/usr'):
        parser.error('compilation requires native ARM64 Termux')
    simd = args.simd or ('asm' if platform.machine().lower() in ('arm64', 'aarch64') else 'c')
    if simd == 'asm' and platform.machine().lower() not in ('arm64', 'aarch64') and args.compile:
        parser.error('inline ARM64 assembly requires an ARM64 build host')
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'build.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('another build is already using this output directory')
        previous = read_json(out / 'build-report.json')
        report = {'schema': 1, 'profile': 'mario', 'status': 'generating', 'simd': simd,
                  'boot_tested': False, 'runtime_ready': False}
        write_json(out / 'build-report.json', report)
        inputs = {name: input_info(exefs / name) for name in ('main', 'sdk')}
        bases = module_bases(inputs['main']['image_bytes'], inputs['sdk']['image_bytes'])
        generator_id = digest({p: file_hash(ROOT / p) for p in GENERATOR_FILES})
        report.update(inputs=inputs, bases={n: hex(b) for n, b in bases.items()}, modules={})
        extras = []
        for path in sorted(exefs.iterdir()):
            if path.is_file() and path.name not in ('main', 'sdk', 'rtld'):
                with path.open('rb') as stream:
                    if stream.read(4) == b'NSO0':
                        extras.append(path.name)
        report['additional_nso_modules'] = extras
        sources = []
        for name in ('main', 'sdk'):
            module, generated = generate(name, exefs / name, out / 'generated' / name,
                                         inputs[name], bases[name], simd, generator_id)
            report['modules'][name] = module
            sources.extend(generated)
        report['status'] = 'generated_requires_runtime'
        identity = 'mario-full:' + digest({'inputs': inputs, 'bases': bases, 'generator': generator_id,
                                           'headers': {p: file_hash(ROOT / p) for p in HEADERS},
                                           'entry': file_hash(ROOT / 'tools/mario_test_entry.c'),
                                           'simd': simd})[:24]
        report['library_id'] = identity
        write_json(out / 'build-report.json', report)
        if args.compile:
            link, built, total = compile_library(out, sources, identity, args.jobs, args.cc,
                                                 args.nm, args.host_test, previous.get('link', {}))
            report.update(status='linked_requires_runtime', link=link,
                          compiled_objects=built, reused_objects=total - built)
            print(f'Objetos compilados: {built}/{total}; reutilizados: {total - built}', flush=True)
            print(f'BIBLIOTECA={out / "libmario_test.so"}', flush=True)
        write_json(out / 'build-report.json', report)
        print(f'RELATORIO={out / "build-report.json"}', flush=True)
        if extras:
            print('Modulos NSO adicionais ainda sem integracao: ' + ', '.join(extras), flush=True)
        print('Etapa: gerador completo main/sdk. Integracao de boot Android ainda pendente.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'ERRO: {error}')
