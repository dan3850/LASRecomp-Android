"""Reproduce a missing interior SDK entry, then execute the actual repair."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_mario_boot_profile as boot
from test_mario_full_recompiler import ROOT, make_nso

sys.path.insert(0, str(ROOT / 'tools'))
import mario_resume_repair as fix
from mario_boot_profile import START_ABIS, prepare
from mario_full_recompile import HEADERS, digest, file_hash


@unittest.skipUnless(shutil.which('clang'), 'Clang required')
class TestMarioResume(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mario-resume-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.exefs, self.out, self.config = (self.folder / name for name in ('exefs', 'code', 'profile'))
        make_nso(self.exefs / 'main')
        make_nso(self.exefs / 'sdk', sdk=True, entry_name=START_ABIS[1][0])
        sdk = bytearray((self.exefs / 'sdk').read_bytes())
        # Entry adds 5 to x4. The interior entry must skip that instruction,
        # add 11 to x0 and RET through the original guest LR.
        struct.pack_into('<II', sdk, 0x100 + 0x44, 0x91002C00, 0xD65F03C0)
        (self.exefs / 'sdk').write_bytes(sdk)
        self.report = self.build()
        prepare(self.out / 'build-report.json', self.exefs, self.config, host_test=True)

    def build(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/mario_full_recompile.py'),
                                 str(self.exefs), '--output', str(self.out), '--compile',
                                 '--simd', 'c', '--host-test'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((self.out / 'build-report.json').read_text())

    def executable(self):
        text = boot.HARNESS.replace('c.x[5]=SDK_BASE+0x40;',
            'c.x[5]=(argc>3 && !strcmp(argv[3],"resume"))?SDK_BASE+0x44:SDK_BASE+0x40;')
        text = text.replace('c.x[0]!=29 || c.x[3]!=29 || memory!=29 || c.x[4]!=5',
            'c.x[0]!=40 || c.x[3]!=40 || memory!=40 || c.x[4]!=(argc>3?0:5)')
        text = text.replace('puts("Mario library loaded;', '''
    // An ordinary direct call must start at the function entry, even if pc
    // still contains an interior address from a previous dispatcher call.
    Cpu direct={0}; direct.pc=SDK_BASE+0x44;
    GuestFn ordinary=dispatch_lookup(SDK_BASE+0x40);
    ordinary(&direct);
    if (direct.x[4]!=5 || direct.x[0]!=11) return 9;
    puts("Mario library loaded;''')
        return boot.TestMarioBoot.build_harness(self, source_text=text)

    def run_guest(self, executable, *args):
        return subprocess.run([str(executable), str(self.exefs), str(self.folder), *args],
                              cwd=self.folder, capture_output=True, text=True)

    def test_missing_entry_is_repaired_at_exact_pc_and_only_two_objects_change(self):
        executable = self.executable()
        before = self.run_guest(executable, 'resume')
        self.assertNotEqual(before.returncode, 0)
        self.assertIn('no function at 7004000044', before.stderr)
        objects = {path: path.stat().st_mtime_ns for path in (self.out / 'objects').rglob('*.o')}
        config_stamp = (self.config / 'mario_profile_config.h').stat().st_mtime_ns
        updated, built = fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        self.assertEqual(built, 2)
        self.assertEqual(updated['library_id'], self.report['library_id'])
        self.assertNotEqual(updated['link']['sha256'], self.report['link']['sha256'])
        changed = {str(path.relative_to(self.out / 'objects')) for path, stamp in objects.items()
                   if path.stat().st_mtime_ns != stamp}
        self.assertEqual(changed, {'sdk/sdk_000.o', 'sdk/sdk_table.o'})
        for args in ((), ('resume',)):
            result = self.run_guest(executable, *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prepare(self.out / 'build-report.json', self.exefs, self.config, host_test=True)
        self.assertEqual((self.config / 'mario_profile_config.h').stat().st_mtime_ns, config_stamp)
        library_stamp = (self.out / 'libmario_test.so').stat().st_mtime_ns
        _, built = fix.repair(self.exefs, self.out, [('sdk', 0x48)], host_test=True)
        self.assertEqual(built, 0)
        self.assertEqual((self.out / 'libmario_test.so').stat().st_mtime_ns, library_stamp)
        # The normal complete builder must retain persisted resume entries.
        again = self.build()
        self.assertEqual(again['compiled_objects'], 0)
        result = self.run_guest(executable, 'resume')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_unused_gamelib_header_keys_preserve_generated_objects(self):
        historical = subprocess.check_output(['git', 'show',
            '81acac47a8ca9780f5d2dbe6c223d97a277b5c4d:runtime/gamelib.h'], cwd=ROOT)
        headers = {name: file_hash(ROOT / name) for name in HEADERS}
        headers['runtime/gamelib.h'] = hashlib.sha256(historical).hexdigest()
        compiler = shutil.which('clang')
        version = subprocess.check_output([compiler, '--version'], text=True)
        flags = ['-std=gnu11', '-O1', '-g0', '-fPIC', '-fno-strict-aliasing',
                 '-fvisibility=hidden', '-Wno-unused-label', '-Wno-return-type', '-I' + str(ROOT / 'runtime')]
        sources = [(source, source.relative_to(self.out / 'generated'))
                   for source in (self.out / 'generated').glob('*/*.c')]
        sources.append((ROOT / 'tools/mario_test_entry.c', Path('mario_test_entry.c')))
        for source, relative in sources:
            source_flags = flags if relative.name != 'mario_test_entry.c' else [
                *flags, '-DGAMELIB_ID=' + json.dumps(self.report['library_id'])]
            old_key = digest({'source': file_hash(source), 'headers': headers,
                              'compiler': compiler, 'version': version, 'flags': source_flags})
            (self.out / 'objects' / relative.with_suffix('.json')).write_text(json.dumps({'key': old_key}))
        _, built = fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        # The entry C really includes gamelib.h; only that extra object rebuilds.
        self.assertEqual(built, 3)
        result = self.run_guest(self.executable(), 'resume')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_resume_entry_can_execute_an_unresolved_local_indirect_branch(self):
        sdk = bytearray((self.exefs / 'sdk').read_bytes())
        struct.pack_into('<4I', sdk, 0x140, 0xF9400046, 0xD61F00C0, 0x91002C00, 0xD65F03C0)
        (self.exefs / 'sdk').write_bytes(sdk)
        self.report = self.build()
        prepare(self.out / 'build-report.json', self.exefs, self.config, host_test=True)
        text = boot.HARNESS.replace('    dispatch_init();', '''    dispatch_init();
    if (argc>3 && !strcmp(argv[3],"data-br")) {
        Cpu c={0}; c.x[6]=SDK_BASE+0x48; c.x[30]=0x1234; c.pc=SDK_BASE+0x44;
        rt_dispatch(&c);
        return c.x[0]!=11 || c.x[30]!=0x1234;
    }
''')
        executable = boot.TestMarioBoot.build_harness(self, source_text=text)
        before = self.run_guest(executable, 'data-br')
        self.assertNotEqual(before.returncode, 0)
        self.assertIn('no function at 7004000044', before.stderr)
        fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        result = self.run_guest(executable, 'data-br')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_resume_inline_simd_sources_compile_for_android_arm64(self):
        output = self.folder / 'arm64'
        generated = subprocess.run([sys.executable, str(ROOT / 'tools/gen.py'), 'main',
                                    str(self.exefs / 'main'), '0x7000000000', str(output),
                                    '--profile', 'mario', '--simd', 'asm',
                                    '--resume-at', '0x7000000204'], capture_output=True, text=True)
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        include = self.folder / 'include'
        include.mkdir()
        (include / 'string.h').write_text('#include <stddef.h>\n'
            'void *memcpy(void *, const void *, size_t);\nvoid *memset(void *, int, size_t);\n')
        resource = subprocess.check_output(['clang', '-print-resource-dir'], text=True).strip()
        for source in output.glob('*.c'):
            result = subprocess.run(['clang', '--target=aarch64-linux-android24', '-ffreestanding',
                                     '-nostdinc', '-isystem', str(Path(resource) / 'include'),
                                     '-I' + str(include), '-I' + str(ROOT / 'runtime'),
                                     '-O1', '-c', str(source), '-o', str(source.with_suffix('.o'))],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(struct.unpack_from('<H', source.with_suffix('.o').read_bytes(), 18)[0], 183)

    def test_failed_repair_restores_completed_library_sources_and_metadata(self):
        paths = [self.out / 'build-report.json', self.out / 'libmario_test.so',
                 *(self.out / 'generated').glob('*/*')]
        snapshots = {path: path.read_bytes() for path in paths if path.is_file()}
        library_mtime = (self.out / 'libmario_test.so').stat().st_mtime_ns

        def fail(*args, **kwargs):
            temporary = self.out / 'invalid.so.partial'
            temporary.write_bytes(b'not a finished library')
            temporary.replace(self.out / 'libmario_test.so')
            raise RuntimeError('interrupted compiler/link operation')

        with patch.object(fix.os, 'link', None), patch.object(fix, 'compile_library', side_effect=fail), self.assertRaisesRegex(RuntimeError, 'interrupted'):
            fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        for path, data in snapshots.items():
            self.assertEqual(path.read_bytes(), data, str(path))
        self.assertFalse((self.out / 'resume-transaction').exists())
        self.assertFalse((self.out / 'resume-plan.json').exists())
        self.assertEqual((self.out / 'libmario_test.so').stat().st_mtime_ns, library_mtime)

    def test_missing_os_link_repairs_and_executes_interior_entry(self):
        executable = self.executable()
        with patch.dict(fix.os.__dict__):
            fix.os.__dict__.pop('link', None)
            _, built = fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        self.assertEqual(built, 2)
        result = self.run_guest(executable, 'resume')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.out / 'resume-transaction').exists())

    def test_rejected_hardlink_uses_verified_copy(self):
        source = self.out / 'libmario_test.so'
        backup = self.folder / 'backup.so'
        with patch.object(fix.os, 'link', side_effect=OSError('not supported')):
            fix.backup_library(source, backup)
        self.assertEqual(backup.read_bytes(), source.read_bytes())
        self.assertEqual(backup.stat().st_mtime_ns, source.stat().st_mtime_ns)

    def test_failed_backup_leaves_completed_build_unchanged(self):
        paths = [self.out / 'build-report.json', self.out / 'libmario_test.so',
                 *(self.out / 'generated').glob('*/*')]
        snapshots = {path: path.read_bytes() for path in paths if path.is_file()}
        with patch.object(fix.os, 'link', None), patch.object(fix.shutil, 'copy2', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        for path, data in snapshots.items():
            self.assertEqual(path.read_bytes(), data, str(path))
        self.assertFalse((self.out / 'resume-transaction').exists())

    def test_edited_sources_and_invalid_targets_do_not_change_library(self):
        library_hash = file_hash(self.out / 'libmario_test.so')
        with self.assertRaisesRegex(ValueError, 'outside compiled text'):
            fix.repair(self.exefs, self.out, [('sdk', 0x5000)], host_test=True)
        source = self.out / 'generated/sdk/sdk_000.c'
        source.write_text(source.read_text() + '\n/* local work */\n')
        with self.assertRaisesRegex(ValueError, 'locally edited'):
            fix.repair(self.exefs, self.out, [('sdk', 0x44)], host_test=True)
        self.assertEqual(file_hash(self.out / 'libmario_test.so'), library_hash)


if __name__ == '__main__':
    unittest.main(verbosity=2)
