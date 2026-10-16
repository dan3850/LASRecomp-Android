#!/usr/bin/env python3
"""Test Git preservation/update flow with a simulated build, not an Android compiler."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'compilar-lasrecomp-pasta-externa.sh'
BRANCH = 'android/external-game-folder'
STABLE = 'android/termux-native-build'
URL = 'https://github.com/dan3850/LASRecomp-Android.git'


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='las-termux-update-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bare = self.root / 'origin.git'
        self.seed = self.root / 'seed'
        self.project = self.root / 'project'
        self.command('git', 'init', '--bare', str(self.bare))
        self.command('git', 'init', '-b', STABLE, str(self.seed))
        self.git(self.seed, 'config', 'user.name', 'Test')
        self.git(self.seed, 'config', 'user.email', 'test@localhost')
        (self.seed / '.gitignore').write_text('build/\ncache/\n')
        (self.seed / 'engine.c').write_text('old engine\n')
        (self.seed / 'settings.txt').write_text('original settings\n')
        (self.seed / 'compilar-lasrecomp-termux.sh').write_text(
            '#!/usr/bin/env bash\nset -eu\nmkdir -p build/termux-native\n'
            'printf "simulated APK" > build/termux-native/LASRecomp-Android-Termux.apk\n')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'baseline')
        self.baseline = self.git(self.seed, 'rev-parse', 'HEAD').stdout.strip()
        self.git(self.seed, 'branch', BRANCH)
        self.git(self.seed, 'remote', 'add', 'origin', str(self.bare))
        self.git(self.seed, 'push', 'origin', STABLE, BRANCH)
        self.command('git', 'clone', '--branch', BRANCH, str(self.bare), str(self.project))
        self.git(self.project, 'remote', 'set-url', 'origin', URL)
        self.git(self.project, 'config', f'url.file://{self.bare}.insteadOf', URL)
        self.git(self.seed, 'switch', BRANCH)
        (self.seed / 'engine.c').write_text('new engine\n')
        self.git(self.seed, 'commit', '-am', 'remote update')
        self.git(self.seed, 'push', 'origin', BRANCH)
        self.updated = self.git(self.seed, 'rev-parse', 'HEAD').stdout.strip()
        fake = self.root / 'bin'
        fake.mkdir()
        (fake / 'uname').write_text('#!/bin/sh\nprintf "aarch64\\n"\n')
        (fake / 'uname').chmod(0o755)
        self.env = dict(os.environ)
        self.env.update(PATH=str(fake) + os.pathsep + self.env['PATH'],
                        PREFIX='/data/data/com.termux/files/usr',
                        LASRECOMP_PROJECT=str(self.project),
                        LASRECOMP_BACKUP_DIR=str(self.root / 'backups'),
                        LASRECOMP_OUTPUT=str(self.root / 'output'))
        self.cache = self.project / 'build/termux-native/obj/cached.o'
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(b'keep compiled cache')
        self.cache_mtime = self.cache.stat().st_mtime_ns

    @staticmethod
    def command(*cmd, cwd=None, env=None, check=True):
        return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=check)

    def git(self, cwd, *args, check=True):
        return self.command('git', *args, cwd=cwd, check=check)

    def build(self):
        return self.command('bash', str(SCRIPT), cwd=self.project, env=self.env, check=False)

    def verify_caches_and_stable(self):
        self.assertEqual(self.cache.read_bytes(), b'keep compiled cache')
        self.assertEqual(self.cache.stat().st_mtime_ns, self.cache_mtime)
        self.assertEqual(self.git(self.seed, 'rev-parse', STABLE).stdout.strip(), self.baseline)
        self.assertEqual(self.git(self.bare, 'rev-parse', 'refs/heads/' + STABLE).stdout.strip(), self.baseline)

    def test_preserves_staged_unstaged_backups_and_source_snapshot(self):
        (self.project / 'settings.txt').write_text('local staged settings\n')
        self.git(self.project, 'add', 'settings.txt')
        build_script = self.project / 'compilar-lasrecomp-termux.sh'
        build_script.write_text(build_script.read_text() + 'printf "local override used\\n"\n')
        expected = build_script.read_text()
        (self.project / 'notes.backup').write_text('untracked backup')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('local override used', result.stdout)
        self.assertEqual(build_script.read_text(), expected)
        self.assertEqual((self.project / 'engine.c').read_text(), 'new engine\n')
        self.assertEqual(self.git(self.project, 'rev-parse', 'HEAD').stdout.strip(), self.updated)
        self.assertEqual(self.git(self.project, 'diff', '--cached', '--name-only').stdout.strip(), 'settings.txt')
        self.assertEqual((self.project / 'notes.backup').read_text(), 'untracked backup')
        backup = next((self.root / 'backups').iterdir())
        self.assertIn('local staged settings', (backup / 'index.patch').read_text())
        self.assertIn('local override used', (backup / 'working-tree.patch').read_text())
        self.assertTrue(self.git(self.project, 'cat-file', '-t', (backup / 'stash.txt').read_text().strip()).stdout.strip() == 'commit')
        archive = next((self.root / 'output').glob('*-local.zip'))
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('compilar-lasrecomp-termux.sh').decode(), expected)
            self.assertEqual(z.read('settings.txt'), b'local staged settings\n')
            self.assertFalse(any(n.startswith('build/') for n in z.namelist()))
        self.verify_caches_and_stable()

    def test_switches_from_stable_without_changing_its_commits(self):
        self.git(self.project, 'switch', STABLE)
        (self.project / 'settings.txt').write_text('local configuration\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.project, 'branch', '--show-current').stdout.strip(), BRANCH)
        self.assertEqual(self.git(self.project, 'rev-parse', STABLE).stdout.strip(), self.baseline)
        self.assertEqual((self.project / 'settings.txt').read_text(), 'local configuration\n')
        self.verify_caches_and_stable()

    def test_already_current_build_keeps_changes_without_another_stash(self):
        self.git(self.project, 'fetch', 'origin', 'refs/heads/' + BRANCH)
        self.git(self.project, 'merge', '--ff-only', 'FETCH_HEAD')
        (self.project / 'settings.txt').write_text('current local configuration\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'backups').exists())
        self.assertEqual((self.project / 'settings.txt').read_text(), 'current local configuration\n')
        self.verify_caches_and_stable()

    def test_conflict_preserves_edits_and_does_not_build(self):
        (self.project / 'engine.c').write_text('different local engine\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Conflito', result.stdout + result.stderr)
        backup = next((self.root / 'backups').iterdir())
        self.assertIn('different local engine', (backup / 'working-tree.patch').read_text())
        self.assertIn('different local engine', (self.project / 'engine.c').read_text())
        self.assertFalse((self.project / 'build/termux-native/LASRecomp-Android-Termux.apk').exists())
        self.verify_caches_and_stable()

    def test_failed_fast_forward_restores_original_local_changes(self):
        (self.seed / 'collision.txt').write_text('remote file\n')
        self.git(self.seed, 'add', 'collision.txt')
        self.git(self.seed, 'commit', '-m', 'add colliding path')
        self.git(self.seed, 'push', 'origin', BRANCH)
        (self.project / 'collision.txt').write_text('keep untracked file\n')
        (self.project / 'settings.txt').write_text('keep tracked changes\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.project, 'rev-parse', 'HEAD').stdout.strip(), self.baseline)
        self.assertEqual((self.project / 'settings.txt').read_text(), 'keep tracked changes\n')
        self.assertEqual((self.project / 'collision.txt').read_text(), 'keep untracked file\n')
        self.assertFalse((self.project / 'build/termux-native/LASRecomp-Android-Termux.apk').exists())
        self.verify_caches_and_stable()

    def test_diverged_history_stops_before_stashing(self):
        self.git(self.project, '-c', 'user.name=Test', '-c', 'user.email=test@localhost',
                 'commit', '--allow-empty', '-m', 'local commit')
        (self.project / 'settings.txt').write_text('keep local edit\n')
        before = self.git(self.project, 'rev-parse', 'HEAD').stdout
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('divergentes', result.stdout + result.stderr)
        self.assertEqual(self.git(self.project, 'rev-parse', 'HEAD').stdout, before)
        self.assertFalse((self.root / 'backups').exists())
        self.assertEqual((self.project / 'settings.txt').read_text(), 'keep local edit\n')
        self.verify_caches_and_stable()


if __name__ == '__main__':
    unittest.main(verbosity=2)
