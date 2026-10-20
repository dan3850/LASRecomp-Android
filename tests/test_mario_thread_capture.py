"""Exercise production thread capture: running code, real waits, missing replies."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MarioThreadCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mario-capture-build-')
        cls.folder = Path(cls.temp.name)
        (cls.folder / 'mario_profile_config.h').write_text('#define GAMELIB_ID "synthetic-capture"\n')
        cls.executable = cls.folder / 'capture'
        result = subprocess.run([
            os.environ.get('CC', 'clang'), '-std=gnu11', '-O1', '-g', '-UNDEBUG',
            '-DLASRECOMP_MARIO_TEST=1', '-ffunction-sections', '-fdata-sections',
            '-Wl,--gc-sections', '-Wno-format', '-Werror=implicit-function-declaration',
            '-I' + str(cls.folder), '-I' + str(ROOT / 'runtime'),
            str(ROOT / 'tests/mario_thread_capture_test.c'), '-pthread', '-ldl', '-o', str(cls.executable),
        ], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def capture(self, mode):
        with tempfile.TemporaryDirectory(prefix='mario-capture-run-') as folder:
            result = subprocess.run([str(self.executable), mode], cwd=folder,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            path = Path(folder) / 'mario-threads.log'
            return path.read_text() if path.exists() else ''

    def test_samples_a_native_loop_without_cooperative_dispatch(self):
        report = self.capture('running')
        self.assertIn('library_id=synthetic-capture', report)
        rows = [line for line in report.splitlines() if line.startswith('thread=80 ')]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn('sampled=1', row)
            self.assertIn('guest_dispatch_pc=7000000040', row)
            self.assertIn('guest_lr=7004000080', row)
            self.assertRegex(row, r'native_pc=[1-9a-f][0-9a-f]* ')
        self.assertIn('sample=1 ', report)
        self.assertIn('sample=2 ', report)
        self.assertIn('complete=1 samples_available=2', report)

    def test_records_condition_mutex_owner_without_waking_or_stealing_it(self):
        report = self.capture('condvar')
        self.assertIn('wait=condvar', report)
        self.assertIn('owner_handle=120 owner_thread=81', report)
        self.assertIn('in_svc=1 svc=1c svc_pc=7004000090', report)

    def test_records_unsignaled_sync_object_without_signaling_it(self):
        report = self.capture('sync')
        self.assertIn('sync_wait=1', report)
        self.assertIn('sync0=121:type2:signaled0', report)

    def test_missing_signal_response_is_explicit_not_stale_registers(self):
        report = self.capture('unanswered')
        rows = [line for line in report.splitlines() if line.startswith('thread=80 ')]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn('sampled=0', row)
            self.assertNotIn('guest_dispatch_pc=', row)

    def test_preserves_an_existing_signal_handler(self):
        self.assertEqual(self.capture('handler'), '')

    def test_rejects_overlapping_capture(self):
        self.assertEqual(self.capture('busy'), '')

    def test_kernel_lock_contention_does_not_hang_the_collector(self):
        report = self.capture('lock')
        self.assertIn('kernel_list=lock_busy', report)
        self.assertIn('samples_available=0', report)

    def test_mutex_word_reader_rejects_unregistered_and_unreadable_memory(self):
        self.assertEqual(self.capture('reader'), '')

    def test_bridge_reports_unavailable_without_a_runtime_callback(self):
        self.assertEqual(self.capture('bridge'), '')

    def test_bridge_waits_for_in_flight_capture_before_clearing_callback(self):
        self.assertEqual(self.capture('bridge-lifetime'), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
