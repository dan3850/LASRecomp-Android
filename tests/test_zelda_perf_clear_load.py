"""Real pinned render functions and recorder, with a delayed pixel model."""
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


PATCH = module('clear_load_patch', ROOT / 'tools/patch_scarletnx_zelda_clear_load.py')


def function(text, signature):
    start = text.index(signature)
    first = text[start:].splitlines()[0]
    return first + '\n' if first.endswith('}') else text[start:text.index('\n}\n', start) + 3]


def patched(name, text):
    for old, new in PATCH.replacements()[name]:
        if text.count(old) != 1:
            raise AssertionError('pinned clear-load source mismatch: ' + name)
        text = text.replace(old, new, 1)
    return text


class ClearLoadTests(unittest.TestCase):
    def test_preflight_idempotency_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            original = {}
            for name, pairs in PATCH.replacements().items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                original[name] = '\n/* anchor */\n'.join(old for old, new in pairs)
                target.write_text(original[name])
            PATCH.apply(root)
            once = {name: (root / name).read_bytes() for name in original}
            PATCH.apply(root)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            header = root / 'src/nx/gpu/vk/snx_clear_load.h'
            good = header.read_text(); header.write_text('unknown header')
            with self.assertRaises(ValueError): PATCH.apply(root, True)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            header.write_text(good)
            PATCH.apply(root, True); PATCH.apply(root, True)
            self.assertEqual(original, {name: (root / name).read_text() for name in original})
            (root / 'src/nx/gpu/vk/renderer.c').write_text('unknown source')
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/render.c').read_text(), original['src/nx/gpu/vk/render.c'])
            self.assertFalse(header.exists())

    def test_analyzer_accepts_old_logs_and_requires_complete_clear_windows(self):
        analyzer = module('clear_load_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'clear-test'})]
        for w in (1, 2):
            rows.append(('SNX_PERF_V1', {'window': w, 'elapsed_s': 5 * w, 'duration_ms': 5000}))
            for stream in ('guest_queue', 'render', 'present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': w, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': w, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': w, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': w, 'draws': 2}))
        def log(items): return '\n'.join(tag + ' ' + json.dumps(row) for tag, row in items)
        legacy = analyzer.analyze(log(rows), 0)
        self.assertNotIn('clear_load', legacy)
        meta = ('SNX_CLEAR_LOAD_META_V1', {'enabled': 1, 'immediate': 1})
        summaries = [('SNX_CLEAR_LOAD_V1', {'window': w, 'enabled': 1, 'requests': 5,
                     'folded_commands': 2, 'color_pixels': 96}) for w in (1, 2)]
        result = analyzer.analyze(log(rows + [meta] + summaries), 0)
        self.assertEqual(result['streams'], legacy['streams'])
        self.assertEqual(result['clear_load']['folded_commands'], 4)
        self.assertEqual(result['clear_load']['color_pixels'], 192)
        self.assertEqual(analyzer.analyze(log(rows + [meta, summaries[0]]), 0)['windows'], 1)
        self.assertEqual(analyzer.analyze(log(rows + [meta] + summaries + [summaries[1]]), 0)['windows'], 1)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows + [meta, summaries[0], (summaries[1][0], {**summaries[1][1], 'enabled': 0})]), 0)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_real_render_and_delayed_recorder_preserve_pixels_and_metadata(self):
        def source(name):
            return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)
        render = source('src/nx/gpu/vk/render.c')
        changed = patched('src/nx/gpu/vk/render.c', render)
        record = source('src/nx/gpu/vk/record.c')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'scissor_actual.inc').write_text(function(source('src/nx/gpu/gpu.h'),
                                                             'static inline int r3d_clear_scissored('))
            start = render.index('static struct {')
            state = render[start:render.index('} g_rp;', start) + len('} g_rp;')]
            (root / 'state_actual.inc').write_text(state.replace('static struct {', 'typedef struct {', 1).replace('} g_rp;', '} Rp;'))
            for name, signature in [('end', 'void vk_render_end('), ('begin', PATCH.BEGIN_OLD),
                                    ('feedback_order', 'static int feedback_order('),
                                    ('feedback_done', 'static void feedback_done('), ('clear', 'void vk_render_clear('),
                                    ('target_written', 'static void target_written('), ('zt_written', 'static int zt_written(')]:
                (root / (name + '_actual.inc')).write_text(function(render, signature))
            (root / 'begin_load_changed.inc').write_text(function(changed, PATCH.BEGIN_NEW))
            (root / 'begin_wrapper_changed.inc').write_text(function(changed, PATCH.BEGIN_OLD))
            (root / 'clear_changed.inc').write_text(function(changed, 'void vk_render_clear('))
            end = record.index('} RenderArgs;') + len('} RenderArgs;')
            (root / 'record_state_actual.inc').write_text(record[record.rfind('typedef struct {', 0, end):end])
            for name, signature in [('rendering_run', 'static void rendering_run('), ('record_begin', 'void rec_CmdBeginRendering(')]:
                (root / (name + '_actual.inc')).write_text(function(record, signature))
            binary = root / 'test'
            build = subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                                    '-I' + str(root), '-I' + str(ROOT / 'tools/zelda-perf'),
                                    str(ROOT / 'tests/zelda_clear_load_fixture.c'), '-o', str(binary)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode in ('0', '1', 'invalid'):
                run = subprocess.run([str(binary)], env={**os.environ, 'SNX_VK_CLEAR_LOAD': mode},
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                self.assertIn('CLEAR_LOAD_OK pixel_model_equal=1 metadata_equal=1 delayed_recorder=1 cases=40', run.stdout)
                data = json.loads(next(line.split(' ', 1)[1] for line in run.stdout.splitlines() if line.startswith('SNX_CLEAR_LOAD_V1 ')))
                self.assertEqual(data['enabled'], int(mode == '1'))
                if mode == '1':
                    self.assertGreater(data['folded_commands'], 0)
                    self.assertGreater(data['continued_fallbacks'], 0)
                else:
                    self.assertTrue(all(value == 0 for key, value in data.items() if key not in ('window', 'enabled')))

    def test_signed_clear_profile_requires_all_assets_and_runtime_markers(self):
        import zipfile
        gate = (ROOT / 'compilar-zelda-clears-termux.sh').read_text().split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        assets = ('Zelda-NXNative.txt', 'Zelda-Uniforms.txt', 'Zelda-Clears.txt')
        markers = ('SNX_CLEAR_LOAD_META_V1', 'SNX_UNIFORM_META_V1', 'SNX_TRANSFER_META_V1', 'revision')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.apk'
            for missing in ('', *assets, *markers):
                with zipfile.ZipFile(path, 'w') as z:
                    for asset in assets:
                        if asset != missing: z.writestr('assets/licenses/' + asset, 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                result = subprocess.run([shutil.which('python3') or 'python', '-c', gate, str(path), 'revision'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, missing == '', result.stderr)


if __name__ == '__main__':
    unittest.main()
