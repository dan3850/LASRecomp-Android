"""Run real kernel condition waits with synthetic callers and host pthreads."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KernelConditionVariable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix='kernel-condvar-')
        cls.executable = Path(cls.folder.name) / 'kernel-condvar'
        built = subprocess.run([
            os.environ.get('CC', 'clang'), '-std=gnu11', '-O1', '-g', '-UNDEBUG',
            '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
            '-Wno-format', '-Werror=implicit-function-declaration', '-pthread',
            '-I' + str(ROOT / 'runtime'),
            str(ROOT / 'tests/kernel_condvar_test.c'), '-o', str(cls.executable),
        ], capture_output=True, text=True)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_zero_timeout_leaves_mutex_for_guest_to_acquire(self):
        self.scenario('zero')

    def test_finite_timeout_leaves_mutex_for_guest_to_acquire(self):
        self.scenario('finite')

    def test_success_returns_with_mutex_owned(self):
        self.scenario('signal')

    def test_success_waits_for_mutex_handoff(self):
        self.scenario('handoff')

    def test_timeout_returns_while_other_thread_owns_mutex(self):
        self.scenario('other-owner')

    def test_timeout_during_signaled_mutex_contention(self):
        self.scenario('signal-before-timeout')

    def test_cancellation_does_not_reacquire_or_report_success(self):
        self.scenario('cancelled')


if __name__ == '__main__':
    unittest.main(verbosity=2)
