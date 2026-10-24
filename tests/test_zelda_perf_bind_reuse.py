"""Exact descriptor lookup with the actual cache and delayed recorder."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get('SCARLETNX_TEST_SRC', ROOT.parent / 'ScarletNX-audit'))
PIN = '34853eeae5af132e320adbb0193f13344085bf89'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


PATCH = module('bind_reuse_patch', ROOT / 'tools/patch_scarletnx_zelda_bind_reuse.py')
HELPERS = module('bind_reuse_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')


class BindingReuseTests(unittest.TestCase):
    def test_atomic_preflight_idempotency_and_byte_exact_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = {}
            for name, pairs in PATCH.replacements().items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True)
                original[name] = '\n/* anchor */\n'.join(old for old, new in pairs); p.write_text(original[name])
            PATCH.apply(root); once = {n: (root / n).read_bytes() for n in original}
            PATCH.apply(root); self.assertEqual(once, {n: (root / n).read_bytes() for n in original})
            header = root / 'src/nx/gpu/vk/snx_bind_reuse.h'
            good = header.read_text(); header.write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root, True)
            self.assertEqual(once, {n: (root / n).read_bytes() for n in original})
            header.write_text(good); PATCH.apply(root, True); PATCH.apply(root, True)
            self.assertEqual(original, {n: (root / n).read_text() for n in original})
            (root / 'src/nx/gpu/vk/renderer.c').write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/render.c').read_text(), original['src/nx/gpu/vk/render.c'])
            self.assertFalse(header.exists())

    def test_analyzer_legacy_and_complete_matching_binding_windows(self):
        analyzer = module('binding_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'bindings-test'})]
        for w in (1, 2):
            rows.append(('SNX_PERF_V1', {'window': w, 'elapsed_s': 5 * w, 'duration_ms': 5000}))
            for stream in ('guest_queue', 'render', 'present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': w, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': w, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': w, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': w, 'draws': 2}))
        def log(items): return '\n'.join(tag + ' ' + json.dumps(row) for tag, row in items)
        legacy = analyzer.analyze(log(rows), 0)
        self.assertNotIn('binding_reuse', legacy)
        meta = ('SNX_BIND_REUSE_META_V1', {'enabled': 1, 'slots': 10, 'resolved_checks': 1})
        summaries = [('SNX_BIND_REUSE_V1', {'window': w, 'enabled': 1, 'lookups': 5,
                     'fast_hits': 2, 'original_lookups': 3, 'hash_mix_calls_bypassed': 72}) for w in (1, 2)]
        result = analyzer.analyze(log(rows + [meta] + summaries), 0)
        self.assertEqual(result['streams'], legacy['streams'])
        self.assertEqual(result['binding_reuse']['fast_hits'], 4)
        self.assertEqual(result['binding_reuse']['hash_mix_calls_bypassed'], 144)
        self.assertEqual(analyzer.analyze(log(rows + [meta, summaries[0]]), 0)['windows'], 1)
        self.assertEqual(analyzer.analyze(log(rows + [meta] + summaries + [summaries[1]]), 0)['windows'], 1)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows + [meta, summaries[0], (summaries[1][0], {**summaries[1][1], 'enabled': 0})]), 0)

    def test_signed_binding_profile_requires_all_current_assets_and_markers(self):
        import zipfile
        gate = (ROOT / 'compilar-zelda-bindings-termux.sh').read_text().split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        assets = ('Zelda-NXNative.txt', 'Zelda-Uniforms.txt', 'Zelda-Clears.txt', 'Zelda-UniformExtent.txt', 'Zelda-Bindings.txt')
        markers = ('SNX_BIND_REUSE_META_V1', 'SNX_UB_EXTENT_META_V1', 'SNX_CLEAR_LOAD_META_V1',
                   'SNX_UNIFORM_META_V1', 'SNX_TRANSFER_META_V1', 'revision')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.apk'
            for missing in ('', *assets, *markers):
                with zipfile.ZipFile(path, 'w') as z:
                    for name in assets:
                        if name != missing: z.writestr('assets/licenses/' + name, 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                run = subprocess.run([shutil.which('python3') or 'python', '-c', gate, str(path), 'revision'], capture_output=True, text=True)
                self.assertEqual(run.returncode == 0, missing == '', run.stderr)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_actual_cache_and_delayed_recorder_preserve_all_resolved_bindings(self):
        def source(name):
            return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)
        render = source('src/nx/gpu/vk/render.c'); changed = render
        for old, new in PATCH.replacements()['src/nx/gpu/vk/render.c']:
            self.assertEqual(changed.count(old), 1); changed = changed.replace(old, new, 1)
        # No stage resolution/check/upload/feedback/barrier instruction changed.
        self.assertEqual(HELPERS.function(render, 'static VkDescriptorSet stage_set('),
                         HELPERS.function(changed, 'static VkDescriptorSet stage_set('))
        record = source('src/nx/gpu/vk/record.c')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            end = render.index('} DescWrites;') + len('} DescWrites;')
            start = render.rfind('typedef struct {', 0, end)
            (root / 'desc_types_actual.inc').write_text(render[start:end])
            vk = source('src/nx/gpu/vk/vk.h')
            frames = next(x for x in vk.splitlines() if x.startswith('#define VK_FRAMES '))
            start = record.index('#define REC_SETS '); end = record.index('static int rec_set_standin(')
            state = record[start:end]
            end = record.index('} NewSetArgs;') + len('} NewSetArgs;')
            start = record.rfind('typedef struct {', 0, end)
            (root / 'record_types_actual.inc').write_text(frames + '\n' + state + '\n' + record[start:end])
            for name, signature in [('write_size', 'static u64 write_info_size('), ('write_info', 'static const void* write_info('),
                                    ('standin', 'static int rec_set_standin('), ('real', 'static VkDescriptorSet rec_set_real(VkDescriptorSet s) {'),
                                    ('new_run', 'static void new_set_run('), ('new_set', 'VkDescriptorSet vk_rec_new_set('),
                                    ('frame_reset', 'static void frame_reset_run('), ('reset', 'void vk_rec_frame_reset(')]:
                (root / (name + '_actual.inc')).write_text(HELPERS.function(record, signature))
            (root / 'mix_actual.inc').write_text(HELPERS.function(render, 'static u64 dset_mix('))
            (root / 'baseline_actual.inc').write_text(HELPERS.function(render, PATCH.OLD).replace('desc_set_cached(', 'baseline_cached(', 1))
            (root / 'original_changed.inc').write_text(HELPERS.function(changed, PATCH.NEW))
            binary = root / 'test'
            build = subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                                    '-I' + str(root), '-I' + str(SRC / 'src'), '-I' + str(ROOT / 'tools/zelda-perf'),
                                    str(ROOT / 'tests/zelda_bind_reuse_fixture.c'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode in ('0', '1', 'invalid'):
                run = subprocess.run([str(binary)], env={**os.environ, 'SNX_VK_BIND_REUSE': mode},
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                self.assertIn('BIND_REUSE_OK scenes=50 bindings=3200 resolved_descriptors_equal=1 delayed_recorder=1 frame_lifetime=1', run.stdout)
                data = json.loads(next(line.split(' ', 1)[1] for line in run.stdout.splitlines() if line.startswith('SNX_BIND_REUSE_V1 ')))
                self.assertEqual(data['enabled'], int(mode == '1'))
                if mode == '1':
                    self.assertGreater(data['fast_hits'], 0)
                    self.assertGreater(data['hash_mix_calls_bypassed'], 0)
                    self.assertGreater(data['key_refusals'], 0)
                    self.assertEqual(data['lookups'], data['fast_hits'] + data['original_lookups'])
                else:
                    self.assertTrue(all(v == 0 for k, v in data.items() if k not in ('window', 'enabled')))


if __name__ == '__main__':
    unittest.main()
