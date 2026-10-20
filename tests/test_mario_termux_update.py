#!/usr/bin/env python3
"""Exercise the real updater with local Git remotes and a simulated APK builder."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'atualizar-compilar-mario-termux.sh'
BRANCH = 'android/mario-full-recompiler-test'
SOURCE = 'android/termux-native-build'
URL = 'https://github.com/dan3850/LASRecomp-Android.git'


class MarioTermuxUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mario-termux-update-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bare = self.root / 'origin.git'
        self.seed = self.root / 'seed'
        self.project = self.root / 'project'
        self.command('git', 'init', '--bare', str(self.bare))
        self.command('git', 'init', '-b', SOURCE, str(self.seed))
        self.git(self.seed, 'config', 'user.name', 'Test')
        self.git(self.seed, 'config', 'user.email', 'test@localhost')
        fixtures = {
            '.gitignore': 'build/\n__pycache__/\n',
            'engine.c': 'old engine\n',
            'runtime/kernel.c': 'synthetic kernel\n',
            'settings.txt': 'original settings\n',
            'tests/test_kernel_condvar.py': 'print("simulated kernel check")\n',
            'tests/test_mario_thread_capture.py': 'print("simulated thread-capture check")\n',
            'tests/kernel_condvar_test.c': 'synthetic test\n',
            'tests/test_mario_boot_profile.py':
                'import unittest\nclass Fixture(unittest.TestCase):\n'
                '    def test_fixture(self): self.assertTrue(True)\n',
            'compilar-mario-full-test-termux.sh':
                '#!/usr/bin/env bash\nset -eu\nmkdir -p build/private-mario-full-test\n'
                'printf "synthetic library" > build/private-mario-full-test/libmario_test.so\n'
                'printf "{}" > build/private-mario-full-test/build-report.json\n'
                'touch build/full-builder-called\n',
            'compilar-mario-boot-termux.sh':
                '#!/usr/bin/env bash\nset -eu\nmkdir -p build/mario-android-boot\n'
                'printf "simulated APK" > build/mario-android-boot/Mario-Recomp-Boot-Test.apk\n'
                'git branch --show-current > build/built-branch\n'
                'cp settings.txt build/built-settings\n'
                'printf "%s" "${MARIO_RESUME_AT-}" > build/received-resume-target\n'
                'printf "%s" "${MARIO_BATCH_ANCHOR-}" > build/received-batch-anchor\n'
                'printf "%s" "${MARIO_BATCH_RETURN_SITE-}" > build/received-batch-return-site\n',
        }
        for name, content in fixtures.items():
            path = self.seed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'baseline')
        self.baseline = self.git(self.seed, 'rev-parse', 'HEAD').stdout.strip()
        self.git(self.seed, 'branch', BRANCH)
        self.git(self.seed, 'remote', 'add', 'origin', str(self.bare))
        self.git(self.seed, 'push', 'origin', SOURCE, BRANCH)
        self.command('git', 'clone', '--branch', SOURCE, str(self.bare), str(self.project))
        self.git(self.project, 'remote', 'set-url', 'origin', URL)
        self.git(self.project, 'config', f'url.file://{self.bare}.insteadOf', URL)
        self.git(self.seed, 'switch', BRANCH)
        (self.seed / 'engine.c').write_text('new engine\n')
        (self.seed / SCRIPT.name).write_text(SCRIPT.read_text())
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'remote Mario update')
        self.git(self.seed, 'push', 'origin', BRANCH)
        self.updated = self.git(self.seed, 'rev-parse', 'HEAD').stdout.strip()
        fake = self.root / 'bin'
        fake.mkdir()
        (fake / 'uname').write_text('#!/bin/sh\nprintf "aarch64\\n"\n')
        (fake / 'uname').chmod(0o755)
        self.game = self.root / 'game with spaces'
        (self.game / 'exefs').mkdir(parents=True)
        (self.game / 'exefs/main').touch()
        (self.game / 'exefs/sdk').touch()
        self.env = dict(os.environ)
        self.env.update(PATH=str(fake) + os.pathsep + self.env['PATH'],
                        PREFIX='/data/data/com.termux/files/usr',
                        MARIO_PROJECT=str(self.project))
        self.cached = self.project / 'build/private-mario-full-test'
        self.cached.mkdir(parents=True)
        self.cache = self.cached / 'unchanged.o'
        self.cache.write_bytes(b'keep object cache')
        (self.cached / 'libmario_test.so').write_bytes(b'keep private library')
        (self.cached / 'build-report.json').write_text('{}')
        self.cache_state = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                            for p in self.cached.iterdir()}
        self.apk = self.project / 'build/mario-android-boot/Mario-Recomp-Boot-Test.apk'

    @staticmethod
    def command(*cmd, cwd=None, env=None, check=True):
        return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True,
                              check=check, timeout=30)

    def git(self, cwd, *args, check=True):
        return self.command('git', *args, cwd=cwd, check=check)

    def build(self):
        # The real script is outside the simulated checkout, exactly as when a
        # launcher extracts it from origin before changing branches.
        return self.command('bash', str(SCRIPT), str(self.game),
                            cwd=self.project, env=self.env, check=False)

    def local_mario(self):
        self.git(self.project, 'branch', BRANCH, self.baseline)

    def edits(self):
        (self.project / 'settings.txt').write_text('staged settings\n')
        self.git(self.project, 'add', 'settings.txt')
        (self.project / 'settings.txt').write_text('unstaged settings\n')
        (self.project / 'notes.backup').write_bytes(b'untracked backup\0\xff')

    def verify_edits(self):
        self.assertEqual((self.project / 'settings.txt').read_text(), 'unstaged settings\n')
        self.assertEqual(self.git(self.project, 'show', ':settings.txt').stdout,
                         'staged settings\n')
        self.assertEqual((self.project / 'notes.backup').read_bytes(), b'untracked backup\0\xff')

    def verify_caches_and_source(self):
        for path, (data, mtime) in self.cache_state.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (data, mtime))
        self.assertEqual(self.git(self.project, 'rev-parse', SOURCE).stdout.strip(), self.baseline)
        self.assertEqual(self.git(self.bare, 'rev-parse', SOURCE).stdout.strip(), self.baseline)
        self.assertFalse((self.project / 'build/full-builder-called').exists())

    def verify_built(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.project, 'branch', '--show-current').stdout.strip(), BRANCH)
        self.assertEqual(self.git(self.project, 'rev-parse', 'HEAD').stdout.strip(), self.updated)
        self.assertEqual((self.project / 'build/built-branch').read_text().strip(), BRANCH)
        self.assertTrue(self.apk.exists())
        self.verify_caches_and_source()

    def backup(self):
        folders = list((self.project / '.git/mario-update-backups').iterdir())
        self.assertEqual(len(folders), 1)
        return folders[0]

    def test_switches_existing_local_branch_and_fast_forwards(self):
        self.local_mario()
        self.verify_built(self.build())
        self.assertEqual(set(self.git(self.project, 'branch', '--format=%(refname:short)')
                             .stdout.splitlines()), {SOURCE, BRANCH})

    def test_explicit_missing_guest_entry_is_forwarded_without_speculative_batch(self):
        self.env['MARIO_RESUME_AT'] = 'main:0x65057c'
        self.verify_built(self.build())
        self.assertEqual((self.project / 'build/received-resume-target').read_text(),
                         'main:0x65057c')

    def test_ordinary_build_without_opt_in_has_no_resume_target(self):
        self.env.pop('MARIO_RESUME_AT', None)
        self.env.pop('MARIO_BATCH_ANCHOR', None)
        self.env.pop('MARIO_BATCH_RETURN_SITE', None)
        self.verify_built(self.build())
        self.assertEqual((self.project / 'build/received-resume-target').read_text(), '')
        self.assertEqual((self.project / 'build/received-batch-anchor').read_text(), '')
        self.assertEqual((self.project / 'build/received-batch-return-site').read_text(), '')

    def test_explicit_bounded_batch_reentry_is_forwarded(self):
        self.env['MARIO_BATCH_ANCHOR'] = 'main:0x687b48'
        self.env['MARIO_BATCH_RETURN_SITE'] = 'main:0x686954'
        self.verify_built(self.build())
        self.assertEqual((self.project / 'build/received-batch-anchor').read_text(),
                         'main:0x687b48')
        self.assertEqual((self.project / 'build/received-batch-return-site').read_text(),
                         'main:0x686954')

    def test_batch_return_site_without_anchor_fails_before_build(self):
        self.env.pop('MARIO_BATCH_ANCHOR', None)
        self.env['MARIO_BATCH_RETURN_SITE'] = 'main:0x686954'
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exige MARIO_BATCH_ANCHOR', result.stdout + result.stderr)
        self.assertFalse(self.apk.exists())
        self.verify_caches_and_source()

    def test_checks_out_existing_remote_branch_when_not_local(self):
        self.verify_built(self.build())
        self.assertEqual(self.git(self.project, 'rev-parse', '--abbrev-ref', '@{upstream}')
                         .stdout.strip(), 'origin/' + BRANCH)

    def test_launcher_loads_updater_missing_from_current_branch(self):
        self.assertFalse((self.project / SCRIPT.name).exists())
        result = self.command('bash', '-c', '''
set -euo pipefail
MARIO_BRANCH="android/mario-full-recompiler-test"
git fetch --no-tags origin "refs/heads/$MARIO_BRANCH:refs/remotes/origin/$MARIO_BRANCH"
MARIO_RUNNER="$(mktemp)"
trap 'rm -f "$MARIO_RUNNER"' EXIT
git show "refs/remotes/origin/$MARIO_BRANCH:atualizar-compilar-mario-termux.sh" > "$MARIO_RUNNER"
MARIO_PROJECT="$PWD" bash "$MARIO_RUNNER" "$1"
''', 'mario-update-test', str(self.game), cwd=self.project, env=self.env, check=False)
        self.verify_built(result)

    def test_keeps_other_branch_edits_in_local_backup_without_mixing_into_mario(self):
        self.local_mario()
        (self.project / 'settings.txt').write_text('older stash\n')
        self.git(self.project, '-c', 'user.name=Test', '-c', 'user.email=test@localhost',
                 'stash', 'push', '-m', 'preexisting stash')
        old_stash = self.git(self.project, 'rev-parse', 'refs/stash').stdout.strip()
        self.edits()
        self.verify_built(self.build())
        self.assertEqual((self.project / 'build/built-settings').read_text(), 'original settings\n')
        self.assertFalse((self.project / 'notes.backup').exists())
        backup = self.backup()
        self.assertEqual((backup / 'origem.txt').read_text().splitlines(), [SOURCE, self.baseline])
        saved = (backup / 'stash.txt').read_text().strip()
        self.assertNotEqual(saved, old_stash)
        self.assertIn(old_stash, self.git(self.project, 'stash', 'list', '--format=%H').stdout)
        self.git(self.project, 'switch', SOURCE)
        self.git(self.project, 'stash', 'apply', '--index', saved)
        self.verify_edits()
        self.verify_caches_and_source()

    def test_restores_mario_staged_unstaged_and_untracked_edits_after_update(self):
        self.local_mario()
        self.git(self.project, 'switch', BRANCH)
        self.edits()
        self.verify_built(self.build())
        self.verify_edits()
        self.assertEqual((self.project / 'build/built-settings').read_text(), 'unstaged settings\n')
        self.assertTrue((self.backup() / 'stash.txt').exists())

    def test_current_mario_keeps_edits_without_creating_another_stash(self):
        self.git(self.project, 'fetch', 'origin', BRANCH)
        self.git(self.project, 'switch', '--track', 'origin/' + BRANCH)
        self.edits()
        self.verify_built(self.build())
        self.verify_edits()
        self.assertFalse((self.project / '.git/mario-update-backups').exists())

    def test_conflicting_mario_edit_stops_before_build_and_keeps_backup(self):
        self.local_mario()
        self.git(self.project, 'switch', BRANCH)
        (self.project / 'engine.c').write_text('different local engine\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflito', result.stdout + result.stderr)
        self.assertFalse(self.apk.exists())
        self.assertIn('different local engine', (self.project / 'engine.c').read_text())
        saved = (self.backup() / 'stash.txt').read_text().strip()
        self.assertEqual(self.git(self.project, 'show', saved + ':engine.c').stdout,
                         'different local engine\n')
        self.verify_caches_and_source()

    def test_failed_fast_forward_restores_source_edits_and_protects_ignored_cache(self):
        self.local_mario()
        (self.seed / 'build').mkdir()
        (self.seed / 'build/protected.bin').write_bytes(b'remote tracked file')
        self.git(self.seed, 'add', '-f', 'build/protected.bin')
        self.git(self.seed, 'commit', '-m', 'colliding path')
        self.git(self.seed, 'push', 'origin', BRANCH)
        protected = self.project / 'build/protected.bin'
        protected.write_bytes(b'keep ignored cache')
        self.edits()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.apk.exists())
        self.assertEqual(self.git(self.project, 'branch', '--show-current').stdout.strip(), SOURCE)
        self.assertEqual(self.git(self.project, 'rev-parse', BRANCH).stdout.strip(), self.baseline)
        self.assertEqual(protected.read_bytes(), b'keep ignored cache')
        self.verify_edits()
        self.assertTrue((self.backup() / 'stash.txt').exists())
        self.verify_caches_and_source()

    def test_diverged_mario_history_stops_before_stashing_or_switching(self):
        self.local_mario()
        self.git(self.project, 'switch', BRANCH)
        self.git(self.project, '-c', 'user.name=Test', '-c', 'user.email=test@localhost',
                 'commit', '--allow-empty', '-m', 'keep local commit')
        local_commit = self.git(self.project, 'rev-parse', 'HEAD').stdout.strip()
        self.git(self.project, 'switch', SOURCE)
        self.edits()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('commits locais fora do origin', result.stdout + result.stderr)
        self.assertEqual(self.git(self.project, 'branch', '--show-current').stdout.strip(), SOURCE)
        self.assertEqual(self.git(self.project, 'rev-parse', BRANCH).stdout.strip(), local_commit)
        self.assertFalse((self.project / '.git/mario-update-backups').exists())
        self.assertFalse(self.apk.exists())
        self.verify_edits()
        self.verify_caches_and_source()

    def test_detached_source_edits_are_preserved_without_mixing(self):
        self.git(self.project, 'switch', '--detach', self.baseline)
        self.edits()
        self.verify_built(self.build())
        backup = self.backup()
        self.assertEqual((backup / 'origem.txt').read_text().splitlines(), ['', self.baseline])
        self.git(self.project, 'switch', '--detach', self.baseline)
        self.git(self.project, 'stash', 'apply', '--index', (backup / 'stash.txt').read_text().strip())
        self.verify_edits()

    def test_pending_git_operation_is_left_untouched(self):
        (self.project / '.git/MERGE_HEAD').write_text(self.baseline + '\n')
        self.edits()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('operacao Git pendente', result.stdout + result.stderr)
        self.assertEqual((self.project / '.git/MERGE_HEAD').read_text(), self.baseline + '\n')
        self.assertFalse(self.apk.exists())
        self.verify_edits()
        self.verify_caches_and_source()

    def test_full_library_is_generated_only_when_missing(self):
        (self.cached / 'libmario_test.so').unlink()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.project / 'build/full-builder-called').exists())
        self.assertEqual(self.cache.read_bytes(), b'keep object cache')
        self.assertEqual(self.cache.stat().st_mtime_ns, self.cache_state[self.cache][1])
        self.assertTrue(self.apk.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
