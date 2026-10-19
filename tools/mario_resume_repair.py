#!/usr/bin/env python3
"""Add exact interior SDK/main entries without regenerating other C chunks."""
import argparse
import bisect
import copy
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from gen import Module, fname, resume_name, table_source
from mario_boot_profile import prepare
from mario_full_recompile import ROOT, compile_library, file_hash, read_json, write_json
from nso import Nso


def parse_table(text, name):
    addresses = re.search(r'const uint64_t ' + name + r'_fn_addrs\[\] = \{(.*?)\};', text, re.S)
    functions = re.search(r'const GuestFn ' + name + r'_fn_ptrs\[\] = \{(.*?)\};', text, re.S)
    if not addresses or not functions:
        raise ValueError(name + ': unsupported generated function table')
    addrs = [int(value, 16) for value in re.findall(r'0x([0-9a-f]+)(?:ull)?', addresses[1])]
    names = [value.strip() for value in functions[1].split(',') if value.strip()]
    if len(addrs) != len(names) or addrs != sorted(set(addrs)) or not addrs:
        raise ValueError(name + ': invalid generated table')
    return dict(zip(addrs, names))


def function_span(text, function):
    found = re.search(r'^void ' + re.escape(function) + r'\(Cpu \*c\) \{', text, re.M)
    if not found:
        raise ValueError('generated function body missing: ' + function)
    depth, state, cursor = 0, 'code', found.end() - 1
    while cursor < len(text):
        ch, pair = text[cursor], text[cursor:cursor + 2]
        if state == 'code':
            if pair in ('/*', '//'):
                state = pair
                cursor += 2
                continue
            if ch in ('"', "'"):
                state = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if not depth:
                    return found.start(), cursor + 1
        elif state in ('"', "'"):
            if ch == '\\':
                cursor += 2
                continue
            if ch == state:
                state = 'code'
        elif state == '/*' and pair == '*/':
            state = 'code'
            cursor += 2
            continue
        elif state == '//' and ch == '\n':
            state = 'code'
        cursor += 1
    raise ValueError('unterminated generated function: ' + function)


def recover(out):
    transaction = out / 'resume-transaction'
    if not transaction.exists():
        return
    manifest = read_json(transaction / 'transaction.json')
    if manifest.get('kind') != 'mario-resume-v1':
        raise ValueError('unrecognized resume transaction; preserve it for inspection')
    if manifest['phase'] == 'prepared':
        for relative, existed in manifest['files'].items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise ValueError('invalid resume transaction path')
            path = out / relative
            if existed:
                shutil.copyfile(transaction / 'files' / relative, path)
            elif path.exists():
                path.unlink()
        backup = transaction / 'libmario_test.so'
        if backup.exists():
            os.replace(backup, out / 'libmario_test.so')
        print('Reparo interrompido revertido para a biblioteca concluida anterior.', flush=True)
    shutil.rmtree(transaction)


def repair(game, out, targets, *, jobs=2, cc='clang', nm=None, host_test=False):
    game, out = Path(game).expanduser().resolve(), Path(out).expanduser().resolve()
    exefs = game / 'exefs' if (game / 'exefs').is_dir() else game
    if not out.is_dir():
        raise ValueError('completed Mario build directory is required')
    with (out / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover(out)
        report = read_json(out / 'build-report.json')
        # Verify the real input files and the completed .so before touching C.
        with tempfile.TemporaryDirectory(prefix='mario-resume-check-', dir=out) as temp:
            prepare(out / 'build-report.json', exefs, Path(temp), host_test=host_test)
        input_hashes = {name: value['sha256'] for name, value in report['inputs'].items()}
        plan = read_json(out / 'resume-plan.json') or {'schema': 1, 'inputs': input_hashes, 'targets': {}}
        if plan.get('schema') != 1 or plan.get('inputs') != input_hashes:
            raise ValueError('resume plan/input mismatch')
        states, sources = {}, []
        for name in ('main', 'sdk'):
            folder = out / 'generated' / name
            generation = read_json(folder / 'generation.json')
            state = read_json(folder / 'generation-state.json')
            if (not generation.get('complete') or not state.get('sources') or
                    state.get('report_sha256') != file_hash(folder / 'generation.json') or
                    set(generation['sources']) != set(state['sources']) or
                    generation != report['modules'][name]):
                raise ValueError(name + ': generation report/cache mismatch')
            for source in generation['sources']:
                if Path(source).name != source:
                    raise ValueError('invalid generated source name')
                path = folder / source
                if state['sources'][source] != file_hash(path):
                    raise ValueError('generated source was locally edited: ' + str(path))
                sources.append(path)
            states[name] = state
        changed = {}
        updated = copy.deepcopy(report)
        for name in ('main', 'sdk'):
            offsets = sorted({offset for module, offset in targets if module == name})
            if not offsets:
                continue
            base = int(report['bases'][name], 0)
            nso = Nso(exefs / name)
            module = Module(name, None, base, report['simd'], nso=nso, profile='mario')
            folder = out / 'generated' / name
            table_path = folder / (name + '_table.c')
            rows = parse_table(table_path.read_text(), name)
            primary = sorted(pc for pc, function in rows.items() if function == fname(pc))
            owners = set()
            for offset in offsets:
                target = base + offset
                if not module.in_text(target) or not primary or target < primary[0]:
                    raise ValueError(f'{name}+{offset:#x}: target outside compiled text')
                if target in rows:
                    if rows[target].startswith('mario_resume_'):
                        print(f'{name}+{offset:#x}: reentrada ja registrada.', flush=True)
                        continue
                    raise ValueError(f'{name}+{offset:#x}: already has a normal function entry; inspect the APK/library version')
                owners.add(primary[bisect.bisect_right(primary, target) - 1])
            for entry in sorted(owners):
                index = bisect.bisect_right(primary, entry)
                end = primary[index] if index < len(primary) else module.hi
                owner = None
                for path in sources:
                    if path.parent != folder or path == table_path:
                        continue
                    text = changed.get(path)
                    if text is None:
                        text = path.read_text()
                    if re.search(r'^void ' + fname(entry) + r'\(Cpu \*c\) \{', text, re.M):
                        owner = path
                        break
                if owner is None:
                    raise ValueError(f'{name}: no source for containing block {entry:#x}')
                labels, _, tables = module.scan(entry, end)
                body = module.emit_function(entry, end, labels, tables, {}, resume=True)
                if not module._refs.issubset(primary):
                    raise ValueError('repair needs an unregistered direct branch; complete generation is required')
                begin, finish = function_span(text, fname(entry))
                changed[owner] = text[:begin] + '\n'.join(body) + text[finish:]
                for pc in range(entry + 4, end, 4):
                    rows[pc] = resume_name(entry)
                generation = updated['modules'][name]
                generation.setdefault('resume_regions', []).append({'entry': hex(entry), 'end': hex(end)})
                print(f'REENTRADA={name} BLOCO={entry:#x}..{end:#x} FONTE={owner.name} '
                      f'NOVAS_ENTRADAS={(end-entry)//4-1}', flush=True)
            if owners:
                changed[table_path] = table_source(name, sorted(rows.items()))
                generation = updated['modules'][name]
                generation.update(primary_functions=len(primary), functions=len(rows), total_functions=len(rows))
                plan['targets'][name] = sorted(set(plan['targets'].get(name, [])) | {hex(offset) for offset in offsets})
        if not changed:
            return report, 0
        metadata_paths = [out / 'build-report.json', out / 'resume-plan.json']
        for name in ('main', 'sdk'):
            if updated['modules'][name] != report['modules'][name]:
                metadata_paths += [out / 'generated' / name / value for value in
                                   ('generation.json', 'generation-state.json')]
        # A hard link preserves the completed .so without making a large copy.
        transaction = out / 'resume-transaction'
        transaction.mkdir()
        manifest = {'kind': 'mario-resume-v1', 'phase': 'backing-up', 'files': {}}
        write_json(transaction / 'transaction.json', manifest)
        try:
            for path in [*changed, *metadata_paths]:
                relative = str(path.relative_to(out))
                manifest['files'][relative] = path.exists()
                if path.exists():
                    backup = transaction / 'files' / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, backup)
            os.link(out / 'libmario_test.so', transaction / 'libmario_test.so')
            manifest['phase'] = 'prepared'
            write_json(transaction / 'transaction.json', manifest)
            for path, text in changed.items():
                temporary = path.with_suffix(path.suffix + '.partial')
                temporary.write_text(text)
                temporary.replace(path)
            link, built, total = compile_library(out, sources, report['library_id'], jobs, cc, nm,
                                                  host_test, report['link'])
            updated.update(link=link, compiled_objects=built, reused_objects=total-built,
                           resume_plan=plan, boot_tested=False)
            for name in ('main', 'sdk'):
                if updated['modules'][name] == report['modules'][name]:
                    continue
                folder = out / 'generated' / name
                write_json(folder / 'generation.json', updated['modules'][name])
                state = states[name]
                state['sources'] = {source: file_hash(folder / source) for source in updated['modules'][name]['sources']}
                state['report_sha256'] = file_hash(folder / 'generation.json')
                write_json(folder / 'generation-state.json', state)
            write_json(out / 'resume-plan.json', plan)
            write_json(out / 'build-report.json', updated)
            manifest['phase'] = 'committed'
            write_json(transaction / 'transaction.json', manifest)
        except BaseException:
            recover(out)
            raise
        shutil.rmtree(transaction)
        print(f'Objetos recompilados no reparo: {built}/{total}; reutilizados: {total-built}', flush=True)
        print('Biblioteca vinculada aos mesmos NSOs; identidade preservada; SHA256 atualizado.', flush=True)
        return updated, built


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/private-mario-full-test')
    parser.add_argument('--resume-at', action='append', required=True, help='module:relative-offset, e.g. sdk:0x52b89c')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--host-test', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 8:
        parser.error('--jobs must be 1..8')
    targets = []
    for value in args.resume_at:
        matched = re.fullmatch(r'(main|sdk):(0x[0-9a-fA-F]+)', value)
        if not matched:
            parser.error('--resume-at must be main:0xOFFSET or sdk:0xOFFSET')
        targets.append((matched[1], int(matched[2], 16)))
    repair(args.game, args.output, targets, jobs=args.jobs, cc=args.cc, host_test=args.host_test)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit('ERRO: ' + str(error))
