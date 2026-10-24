"""Strict UBO snapshots using the actual pinned buffer and graphics functions."""
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


PATCH = module('uniform_patch', ROOT / 'tools/patch_scarletnx_zelda_uniform.py')


def function(text, signature):
    start = text.index(signature)
    first = text[start:].splitlines()[0]
    return first + '\n' if first.endswith('}') else text[start:text.index('\n}\n', start) + 3]


def patched(name, text):
    for old, new in PATCH.replacements()[name]:
        if text.count(old) != 1:
            raise AssertionError('pinned uniform source mismatch: ' + name)
        text = text.replace(old, new, 1)
    return text


class UniformTests(unittest.TestCase):
    def test_patch_preflights_every_file_and_header_and_restores_exact_bytes(self):
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
            header = root / 'src/nx/gpu/vk/snx_uniform.h'
            good_header = header.read_text()
            header.write_text('unknown header')
            with self.assertRaises(ValueError): PATCH.apply(root, True)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            header.write_text(good_header)
            PATCH.apply(root, True)
            PATCH.apply(root, True)
            self.assertEqual(original, {name: (root / name).read_text() for name in original})
            unknown = root / 'src/nx/gpu/vk/renderer.c'
            unknown.write_text('unknown source')
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/buffer.c').read_text(), original['src/nx/gpu/vk/buffer.c'])
            self.assertFalse(header.exists())

    def test_analyzer_accepts_legacy_and_requires_matching_complete_uniform_windows(self):
        analyzer = module('uniform_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'uniform-test'})]
        for w in (1, 2):
            rows.append(('SNX_PERF_V1', {'window': w, 'elapsed_s': 5 * w, 'duration_ms': 5000}))
            for stream in ('guest_queue', 'render', 'present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': w, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': w, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': w, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': w, 'draws': 2}))
        def log(items): return '\n'.join(tag + ' ' + json.dumps(row) for tag, row in items)
        legacy = analyzer.analyze(log(rows), skip_seconds=0)
        self.assertNotIn('uniforms', legacy)
        meta = ('SNX_UNIFORM_META_V1', {'enabled': 1, 'strict_checks': 1})
        summaries = [('SNX_UNIFORM_V1', {'window': w, 'enabled': 1,
                      'requests': 6, 'reused_snapshots': 2, 'reused_bytes': 8192, 'promotion_bypasses': 1}) for w in (1, 2)]
        result = analyzer.analyze(log(rows + [meta] + summaries), skip_seconds=0)
        self.assertEqual(result['streams'], legacy['streams'])
        self.assertEqual(result['uniforms']['reused_snapshots'], 4)
        self.assertEqual(result['uniforms']['reused_bytes'], 16384)
        self.assertEqual(analyzer.analyze(log(rows + [meta, summaries[0]]), 0)['windows'], 1)
        duplicate = analyzer.analyze(log(rows + [meta] + summaries + [summaries[1]]), 0)
        self.assertEqual(duplicate['windows'], 1)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows + [meta, summaries[0], (summaries[1][0], {**summaries[1][1], 'enabled': 0})]), 0)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_actual_strict_buffer_and_graphics_binding_snapshots(self):
        def source(name):
            return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)
        original = source('src/nx/gpu/vk/buffer.c')
        changed = patched('src/nx/gpu/vk/buffer.c', original)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            start = original.index('typedef struct Vb {')
            (root / 'vb_actual.inc').write_text(original[start:original.index('} Vb;', start) + len('} Vb;')])
            for name, signature in [('own_link', 'static void own_link('), ('own_unlink', 'static void own_unlink('),
                                    ('use', 'static void use('), ('drop_own', 'static void drop_own('),
                                    ('make_own', 'static int make_own('), ('guest_bytes', 'static const u8* guest_bytes('),
                                    ('copy', 'int vk_buf_copy(')]:
                (root / (name + '_actual.inc')).write_text(function(original, signature))
            (root / 'hash_actual.inc').write_text(function(source('src/nx/gpu/vk/cmd.c'), 'u64 vk_hash('))
            (root / 'baseline_actual.inc').write_text(function(original, PATCH.GET_OLD).replace('buf_get(', 'baseline_get(', 1))
            (root / 'optimized_actual.inc').write_text(function(changed, PATCH.GET_NEW))
            wrappers = '\n'.join(function(changed, signature) for signature in
                                 ('int vk_buf_get(', 'int vk_buf_get_strict(', 'int vk_buf_get_uniform('))
            (root / 'wrappers_actual.inc').write_text(wrappers)
            render = source('src/nx/gpu/vk/render.c')
            (root / 'cb_baseline.inc').write_text(function(render, 'static int cb_get(').replace('cb_get(', 'baseline_cb(', 1).replace('vk_buf_get_strict(', 'baseline_strict(', 1))
            (root / 'cb_actual.inc').write_text(function(patched('src/nx/gpu/vk/render.c', render), 'static int cb_get('))
            binary = root / 'test'
            build = subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                                    '-I' + str(root), '-I' + str(ROOT / 'tools/zelda-perf'),
                                    str(ROOT / 'tests/zelda_uniform_fixture.c'), '-o', str(binary)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode in ('0', '1', 'invalid'):
                run = subprocess.run([str(binary)], env={**os.environ, 'SNX_VK_UNIFORM_STREAM': mode},
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                self.assertIn('UNIFORM_OK byte_exact=1 strict_checks=1 old_draws_immutable=1', run.stdout)
                data = json.loads(next(line.split(' ', 1)[1] for line in run.stdout.splitlines() if line.startswith('SNX_UNIFORM_V1 ')))
                self.assertEqual(data['enabled'], int(mode == '1'))
                if mode == '1':
                    self.assertGreater(data['reused_snapshots'], 0)
                    self.assertGreater(data['promotion_bypasses'], 0)
                else:
                    self.assertTrue(all(value == 0 for key, value in data.items() if key not in ('window', 'enabled')))

    def test_signed_uniform_profile_requires_both_current_assets_and_runtime(self):
        import zipfile
        wrapper = (ROOT / 'compilar-zelda-uniformes-termux.sh').read_text()
        gate = wrapper.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.apk'
            for missing in ('', 'Zelda-NXNative.txt', 'Zelda-Uniforms.txt', 'SNX_UNIFORM_META_V1', 'revision'):
                with zipfile.ZipFile(path, 'w') as z:
                    for name in ('Zelda-NXNative.txt', 'Zelda-Uniforms.txt'):
                        if name != missing: z.writestr('assets/licenses/' + name, 'revision')
                    markers = ['SNX_UNIFORM_META_V1', 'SNX_TRANSFER_META_V1', 'revision']
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                result = subprocess.run([shutil.which('python3') or 'python', '-c', gate, str(path), 'revision'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, missing == '', result.stderr)


if __name__ == '__main__':
    unittest.main()
