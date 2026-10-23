"""Compile/execute the real telemetry and validate exported evidence and patch rollback."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PATCH = module('perf_patch', ROOT / 'tools/patch_scarletnx_zelda_perf.py')
ANALYZE = module('perf_analyzer', ROOT / 'tools/analyze_zelda_perf.py')


class PerfPatchTests(unittest.TestCase):
    def test_transactional_apply_idempotency_and_restoration(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            before = {}
            for name, pairs in PATCH.replacements().items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                before[name] = '\n/* next anchor */\n'.join(old for old, new in pairs)
                path.write_text(before[name])
            PATCH.apply(root, 'test-revision')
            once = {name: (root / name).read_text() for name in before}
            PATCH.apply(root, 'test-revision')
            self.assertEqual(once, {name: (root / name).read_text() for name in before})
            PATCH.apply(root, revert=True)
            self.assertEqual(before, {name: (root / name).read_text() for name in before})
            PATCH.apply(root, revert=True)
            last = list(before)[-1]
            (root / last).write_text('unfamiliar source')
            with self.assertRaises(ValueError):
                PATCH.apply(root)
            for name in before:
                self.assertEqual((root / name).read_text(), 'unfamiliar source' if name == last else before[name])
            self.assertFalse((root / 'src/nx/runtime/snx_perf.h').exists())

    @unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
    def test_execute_real_telemetry_and_analyze_pooled_frame_times(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            headers = root / 'nx/runtime'
            headers.mkdir(parents=True)
            cpu = root / 'common/cpu/aarch64'
            cpu.mkdir(parents=True)
            (cpu / 'cpu.h').write_text('#include <stdint.h>\ntypedef uint64_t u64;\n')
            shutil.copy(ROOT / 'tools/zelda-perf/perf.h', headers / 'snx_perf.h')
            (headers / 'snx_perf_build.h').write_text('#define SNX_PERF_REVISION "test-revision"\n')
            source = root / 'test.c'
            source.write_text(r'''
#include <stdint.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
typedef pthread_mutex_t PMutex;
#define PMUTEX_INIT PTHREAD_MUTEX_INITIALIZER
#define pm_lock pthread_mutex_lock
#define pm_unlock pthread_mutex_unlock
#define LOG(...) printf(__VA_ARGS__)
static uint64_t clock_ns = 1;
static uint64_t plat_ns(void) { return clock_ns; }
#include "perf_impl.h"
static void* worker(void* unused) {
    (void)unused;
    for (int i = 0; i < 1000; i++) snx_perf_add(SNX_PM_SUBMIT, 1000, 1);
    return NULL;
}
int main(void) {
    snx_perf_init();
    snx_perf_frame(SNX_PF_RENDER);
    assert(!snx_pf[SNX_PF_RENDER].frames);
    setenv("SNX_PERF", "1", 1);
    snx_perf_init();
    pthread_t threads[4];
    for (int i = 0; i < 4; i++) assert(!pthread_create(&threads[i], NULL, worker, NULL));
    for (int i = 0; i < 4; i++) assert(!pthread_join(threads[i], NULL));
    for (int i = 0; i < 1100; i++) {
        clock_ns += i == 400 ? 60000000 : 10000000;
        snx_perf_frame(SNX_PF_GUEST);
        snx_perf_frame(SNX_PF_PRESENT);
        snx_perf_frame(SNX_PF_RENDER);
    }
    return 0;
}
''')
            binary = root / 'test'
            subprocess.run(['cc', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra', '-Werror',
                            '-pthread', '-I' + str(root), '-I' + str(ROOT / 'tools/zelda-perf'),
                            str(source), '-o', str(binary)], check=True, capture_output=True, text=True)
            text = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
            self.assertTrue(all(len(line.encode()) < 2048 for line in text.splitlines()))
            # A renderer-only snapshot normally follows each flush.
            windows = [json.loads(line.split(' ', 1)[1])['window'] for line in text.splitlines()
                       if line.startswith('SNX_PERF_V1 ')]
            text += ''.join('SNX_VK_V1 ' + json.dumps({'window': w, 'draws': 100}) + '\n' for w in windows)
            result = ANALYZE.analyze(text, skip_seconds=0)
            self.assertEqual(result['windows'], 2)
            self.assertEqual(result['costs']['submit'], {'calls': 4000, 'ms': 4.0})
            self.assertEqual(result['streams']['render']['p95_ms'], 10)
            self.assertEqual(result['streams']['render']['p99_ms'], 10)
            self.assertEqual(result['streams']['render']['max_ms'], 60)
            self.assertEqual(result['streams']['render']['over_50ms'], 1)
            self.assertIsNone(result['displayed_fps'])
            self.assertIsNone(result['simulation_fps'])
            # Android's exporter includes preview copies before the canonical
            # bounded telemetry section. They must not double-count frames.
            exported = text + '\n=== SNX PERF BEGIN ===\n' + text + '=== SNX PERF END ===\n'
            self.assertEqual(ANALYZE.analyze(exported, 0), result)
            with self.assertRaisesRegex(ValueError, 'export truncated'):
                ANALYZE.analyze(exported + 'SNX_PERF_EXPORT_TRUNCATED', 0)
            # A concatenated report cannot silently combine independent runs.
            with self.assertRaisesRegex(ValueError, 'sessions found'):
                ANALYZE.analyze(text + text, skip_seconds=0)
            self.assertEqual(ANALYZE.analyze(text + text, 0, session=2)['session'], 2)
            with self.assertRaisesRegex(ValueError, 'frame chunks'):
                ANALYZE.analyze(text.replace('SNX_FRAMES_V1', 'MISSING', 1), 0)
            with self.assertRaisesRegex(ValueError, 'invalid telemetry'):
                ANALYZE.analyze(text + 'SNX_COST_V1 {\"window\":', 0)
            detailed = text + 'SNX_GFX_META_V1 {"shadows_enabled":1}\n'
            for w in windows:
                detailed += 'SNX_GFX_V1 ' + json.dumps({'window': w, 'null_bindings': w}) + '\n'
            graphics = ANALYZE.analyze(detailed, 0)
            self.assertEqual(graphics['graphics'], {'null_bindings': sum(windows)})
            self.assertEqual(graphics['metadata']['graphics_diagnostics'], {'shadows_enabled': 1})
            self.assertEqual(graphics['streams'], result['streams'])

    def test_zelda_launcher_gate_and_legacy_choice_do_not_silently_activate_backend(self):
        activity = (ROOT / 'android/src/com/retroaura/lasrecomp/MarioSnxGameActivity.java').read_text()
        boot = (ROOT / 'android/src/com/retroaura/lasrecomp/CastlevaniaSnxBootActivity.java').read_text()
        self.assertIn('&& (zelda ||', activity)
        self.assertNotIn('getBoolean("ryujinx_native_probe"', boot)
        self.assertIn('getBoolean("zelda_live_ryujinx", false)', boot)
        self.assertIn('if (hasPerfBuild())', boot)


if __name__ == '__main__':
    unittest.main()
