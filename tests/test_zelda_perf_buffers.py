"""Retired buffer reuse and passive write-watch failure evidence."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get('SCARLETNX_TEST_SRC', ROOT.parent / 'ScarletNX-audit'))
PIN = '34853eeae5af132e320adbb0193f13344085bf89'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


WW = module('buffers_ww', ROOT / 'tools/patch_scarletnx_zelda_ww_diag.py')
VB = module('buffers_vb', ROOT / 'tools/patch_scarletnx_zelda_vb_pool.py')
HELPERS = module('buffers_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')
TRANSFER = module('buffers_transfer', ROOT / 'tools/patch_scarletnx_zelda_transfer.py')


def source(name):
    return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)


def transform(text, pairs):
    for old, new in pairs:
        if text.count(old) != 1: raise AssertionError('unknown source: ' + old[:75])
        text = text.replace(old, new, 1)
    return text


class PersistentBufferTests(unittest.TestCase):
    def test_both_patchers_are_transactional_idempotent_and_restore_exact_bytes(self):
        for patch, header in ((WW, 'runtime/platform/snx_ww_diag.h'), (VB, 'gpu/vk/snx_vb_pool.h')):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); original = {}
                for name, pairs in patch.replacements().items():
                    path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                    original[name] = '\n/* anchor */\n'.join(old for old, new in pairs); path.write_text(original[name])
                patch.apply(root); once = {n: (root / n).read_bytes() for n in original}
                patch.apply(root); self.assertEqual(once, {n: (root / n).read_bytes() for n in original})
                generated = root / 'src/nx' / header
                good = generated.read_text(); generated.write_text('unknown')
                with self.assertRaises(ValueError): patch.apply(root, True)
                self.assertEqual(once, {n: (root / n).read_bytes() for n in original})
                generated.write_text(good); patch.apply(root, True); patch.apply(root, True)
                self.assertEqual(original, {n: (root / n).read_text() for n in original})
                (root / 'src/nx/gpu/vk/renderer.c').write_text('unknown')
                with self.assertRaises(ValueError): patch.apply(root)
                self.assertFalse(generated.exists())
                first = next(n for n in original if n != 'src/nx/gpu/vk/renderer.c')
                self.assertEqual((root / first).read_text(), original[first])

    def test_analyzer_requires_complete_buffers_windows_and_keeps_legacy_metrics(self):
        analyzer = module('buffers_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'buffers'})]
        for w in (1, 2):
            rows.append(('SNX_PERF_V1', {'window': w, 'elapsed_s': 5 * w, 'duration_ms': 5000}))
            for stream in ('guest_queue', 'render', 'present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': w, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': w, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': w, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': w, 'draws': 2}))
        def log(items): return '\n'.join(k + ' ' + json.dumps(v) for k, v in items)
        legacy = analyzer.analyze(log(rows), 0)
        meta = [('SNX_VB_POOL_META_V1', {'enabled': 1}), ('SNX_WW_META_V1', {'policy_changed': 0}),
                ('SNX_WW_EVENT_V1', {'event': 'userfaultfd_failed', 'errno': 1})]
        summaries = [('SNX_VB_POOL_V1', {'window': w, 'enabled': 1, 'requests': 5, 'pool_hits': 2,
                     'allocation_calls': 3, 'pool_bytes': w * 16, 'pool_entries': w}) for w in (1, 2)]
        result = analyzer.analyze(log(rows + meta + summaries), 0)
        self.assertEqual(result['streams'], legacy['streams'])
        self.assertEqual(result['persistent_buffers']['pool_hits'], 4)
        self.assertEqual(result['persistent_buffers']['pool_bytes'], 32)
        self.assertEqual(result['write_watch_events'][0]['errno'], 1)
        self.assertEqual(analyzer.analyze(log(rows + meta + [summaries[0]]), 0)['windows'], 1)
        self.assertEqual(analyzer.analyze(log(rows + meta + summaries + [summaries[1]]), 0)['windows'], 1)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows + meta + [summaries[0], (summaries[1][0], {**summaries[1][1], 'enabled': 0})]), 0)

    def test_signed_profile_requires_current_asset_and_runtime_markers(self):
        gate = (ROOT / 'compilar-zelda-buffers-termux.sh').read_text().split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        markers = ('SNX_VB_POOL_META_V1', 'SNX_WW_META_V1', 'SNX_WW_EVENT_V1', 'revision')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.apk'
            for missing in ('', 'asset', *markers):
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('assets/licenses/Zelda-PersistentBuffers.txt', 'old' if missing == 'asset' else 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                run = subprocess.run([os.sys.executable, '-c', gate, str(path), 'revision'], capture_output=True, text=True)
                self.assertEqual(run.returncode == 0, missing == '', run.stderr)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_actual_posix_calls_and_results_unchanged_across_every_failure_stage(self):
        path = 'src/nx/runtime/platform/plat_posix.c'
        before = source(path); after = transform(before, WW.replacements()[path])
        def region(s): return s[s.index('static int g_pagemap = -1;'):s.index('u64 plat_vm_page(void)')]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); header = root / 'nx/runtime/platform/snx_ww_diag.h'; header.parent.mkdir(parents=True)
            header.write_bytes((ROOT / 'tools/zelda-perf/ww_diag.h').read_bytes())
            results = {}
            for native in (0, 1):
                for diagnostic, text in ((0, before), (1, after)):
                    (root / 'ww_actual.inc').write_text(region(text)); binary = root / f'ww-{native}-{diagnostic}'
                    build = subprocess.run(['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        f'-DNATIVE_UAPI={native}', f'-DDIAGNOSTIC={diagnostic}', '-I' + d,
                        str(ROOT / 'tests/zelda_ww_diag_fixture.c'), '-o', str(binary)], capture_output=True, text=True)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    for mode in ('ok', 'syscall', 'api', 'minor_fallback', 'register', 'pagemap', 'remap', 'scan', 'disabled'):
                        env = dict(os.environ); env.pop('SNX_NO_WW', None)
                        run = subprocess.run([str(binary), mode], env=env, capture_output=True, text=True)
                        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                        trace = [s for s in run.stdout.splitlines() if s.startswith(('TRACE ', 'RESULT '))]
                        if not diagnostic: results[native, mode] = trace
                        else:
                            self.assertEqual(trace, results[native, mode], mode)
                            events = [json.loads(s.split(' ', 1)[1]) for s in run.stdout.splitlines() if s.startswith('SNX_WW_EVENT_V1 ')]
                            expected = 'build_uapi_unavailable' if not native else {
                                'syscall': 'userfaultfd_failed', 'api': 'api_failed', 'register': 'register_failed',
                                'pagemap': 'pagemap_open_failed', 'remap': 'remap_failed', 'scan': 'scan_failed',
                                'disabled': 'disabled_by_env'}.get(mode, 'tracking_registered')
                            self.assertIn(expected, [e['event'] for e in events])
                            self.assertLessEqual(len(events), 16)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_actual_promotions_preserve_inflight_draws_and_reduce_only_allocations(self):
        original = source('src/nx/gpu/vk/buffer.c')
        before = transform(original, TRANSFER.replacements()['src/nx/gpu/vk/buffer.c'])
        after = transform(before, VB.replacements()['src/nx/gpu/vk/buffer.c'])
        self.assertEqual(HELPERS.function(before, 'static int buf_get('), HELPERS.function(after, 'static int buf_get('))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            start = after.index('typedef struct Vb {'); end = after.index('} Vb;', start) + len('} Vb;')
            (root / 'vb_actual.inc').write_text(after[start:end])
            for name, signature in [('own_link', 'static void own_link('), ('own_unlink', 'static void own_unlink('),
                ('drop_own', 'static void drop_own('), ('make_own', 'static int make_own('),
                ('reclaim', 'u64 vk_buf_reclaim('), ('stats', 'void vk_buf_stats(')]:
                (root / (name + '_actual.inc')).write_text(HELPERS.function(after, signature))
            binary = root / 'buffers'
            build = subprocess.run(['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror', '-I' + d,
                '-I' + str(ROOT / 'tools/zelda-perf'), str(ROOT / 'tests/zelda_vb_pool_fixture.c'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            pixels = []
            for mode in ('0', '1', 'invalid'):
                run = subprocess.run([str(binary)], env={**os.environ, 'SNX_VK_VB_POOL': mode}, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                self.assertIn('VB_POOL_OK retired_only=1', run.stdout)
                pixel = next(s for s in run.stdout.splitlines() if s.startswith('DRAW_BYTES ')); pixels.append(pixel.split(' made=')[0])
                metrics = json.loads(next(s.split(' ', 1)[1] for s in run.stdout.splitlines() if s.startswith('SNX_VB_POOL_V1 ')))
                self.assertEqual(metrics['pool_hits'], 147 if mode == '1' else 0)
                self.assertEqual(metrics['allocation_calls'], 3 if mode == '1' else 150)
            self.assertEqual(pixels, [pixels[0]] * 3)


if __name__ == '__main__':
    unittest.main()
