"""Depth evidence: retirement, copy bytes/layers, formats and bounded exports."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get('SCARLETNX_TEST_SRC', ROOT.parent / 'ScarletNX-audit'))
PIN = '34853eeae5af132e320adbb0193f13344085bf89'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


PATCH = module('shadow_patch', ROOT / 'tools/patch_scarletnx_zelda_shadow_capture.py')
ANALYZER = module('shadow_analyzer', ROOT / 'tools/analyze_zelda_shadows.py')
HELPERS = module('shadow_uniform_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')


def metadata(fmt=129, w=2, h=2, layers=1):
    bpp = 2 if fmt in (124, 128) else 4
    return {'schema': 'SNX_SHADOW_DEPTH_V1', 'capture': 1, 'frame': 100, 'image_width': w,
            'image_height': h, 'layers': layers, 'format': fmt, 'mip': 0,
            'bytes': w * h * layers * bpp, 'byte_order': 'little'}


class ShadowCaptureTests(unittest.TestCase):
    def test_preflight_idempotency_and_exact_source_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = {}
            for name, pairs in PATCH.replacements().items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True)
                original[name] = '\n/* anchor */\n'.join(old for old, new in pairs); p.write_text(original[name])
            PATCH.apply(root); once = {n: (root / n).read_bytes() for n in original}
            PATCH.apply(root); self.assertEqual(once, {n: (root / n).read_bytes() for n in original})
            header = root / 'src/nx/gpu/vk/snx_shadow_capture.h'
            good = header.read_text(); header.write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root, True)
            self.assertEqual(once, {n: (root / n).read_bytes() for n in original})
            header.write_text(good); PATCH.apply(root, True); PATCH.apply(root, True)
            self.assertEqual(original, {n: (root / n).read_text() for n in original})
            (root / 'src/nx/gpu/vk/renderer.c').write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/render.c').read_text(), original['src/nx/gpu/vk/render.c'])
            self.assertFalse(header.exists())

    def test_depth_aspect_formats_and_array_layers(self):
        # D24's upper byte is undefined padding, not the guest stencil byte.
        for fmt in (124, 125, 126, 128, 129, 130):
            code, mask = ANALYZER.FORMATS[fmt]
            values = [0, 0, mask, mask, mask, 0, mask, 0] if mask else [0, 0, 1, 1, 1, 0, 1, 0]
            if code == 'I': values = [v | (0xa5 << 24) for v in values]
            raw = struct.pack('<8' + code, *values)
            result = ANALYZER.analyze_pair(metadata(fmt, layers=2), raw)
            for layer in result['layers']:
                self.assertEqual((layer['min'], layer['max'], layer['mean'], layer['zero'], layer['one']), (0, 1, .5, 2, 2))
                self.assertFalse(layer['constant_finite'])
        result = ANALYZER.analyze_pair(metadata(126), struct.pack('<4f', float('nan'), float('inf'), -1, 2))
        self.assertEqual(result['layers'][0]['nonfinite'], 2)
        self.assertEqual(result['layers'][0]['outside_0_1'], 2)
        json.dumps(result, allow_nan=False)
        for changed, raw in [(metadata(), b''), (metadata(w=0), b''), ({**metadata(), 'format': 37}, bytes(16)),
                             ({**metadata(), 'byte_order': 'big'}, bytes(16)), ({**metadata(), 'mip': 1}, bytes(16))]:
            with self.assertRaises(ValueError): ANALYZER.analyze_pair(changed, raw)

    def test_complete_zip_and_orientation_preserving_previews(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive = root / 'capture.zip'; name = 'shadows/00000123456789ab/shadow-1'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(name + '.json', json.dumps(metadata(124)))
                z.writestr(name + '.depth', struct.pack('<4H', 0, 65535, 16384, 32768))
                z.writestr('../../ignored', 'never extract this')
            result = ANALYZER.analyze_archive(archive, root / 'out')
            self.assertEqual(len(result), 1)
            self.assertEqual((root / 'out/shadow-1-layer-0-raw.pgm').read_bytes(), b'P5\n2 2\n255\n\x00\xff\x40\x80')
            self.assertFalse((root.parent / 'ignored').exists())
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(name + '.json', json.dumps(metadata()))
            with self.assertRaisesRegex(ValueError, 'Missing'): ANALYZER.analyze_archive(archive)

    def test_performance_analyzer_refuses_armed_visual_capture_in_selected_session(self):
        perf = module('shadow_perf_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        log = 'SNX_PERF_META_V1 {"revision":"visual"}\nSNX_SHADOW_CAPTURE_V1 {"status":"armed"}\n'
        with self.assertRaisesRegex(ValueError, 'not an FPS comparison'): perf.analyze(log)
        # A separate session must not inherit the first session's capture state.
        log += 'SNX_PERF_META_V1 {"revision":"performance"}\n'
        with self.assertRaises(ValueError) as error: perf.analyze(log, session=2)
        self.assertNotIn('not an FPS comparison', str(error.exception))

    def test_build_gate_and_off_by_default_launcher_wiring(self):
        builder = (ROOT / 'compilar-zelda-sombras-termux.sh').read_text()
        gate = builder.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.apk'
            markers = ('SNX_SHADOW_CAPTURE_V1', 'SNX_SHADOW_DEPTH_V1', 'revision')
            for missing in ('', *markers):
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                run = subprocess.run([os.sys.executable, '-c', gate, str(path), 'revision'], capture_output=True, text=True)
                self.assertEqual(run.returncode == 0, missing == '', run.stderr)
        boot = (ROOT / 'android/src/com/retroaura/lasrecomp/CastlevaniaSnxBootActivity.java').read_text()
        game = (ROOT / 'android/src/com/retroaura/lasrecomp/MarioSnxGameActivity.java').read_text()
        self.assertIn('getBoolean("zelda_shadow_capture_v1", false)', boot)
        self.assertIn('session.getAbsolutePath()', boot)
        self.assertIn('shadowDir == null ? "" : shadowDir', game)
        shared = (ROOT / 'compilar-castlevania-shader-termux.sh').read_text()
        self.assertLess(shared.index('patch_scarletnx_zelda_shadow_capture.py'), shared.index('patch_scarletnx_zelda_bind_reuse.py'))
        applies = shared[shared.index('if [ "${SCARLETNX_ZELDA_PERF:-0}" = 1 ]; then\n  python3'):]
        self.assertLess(applies.index('patch_scarletnx_zelda_bind_reuse.py'), applies.index('patch_scarletnx_zelda_shadow_capture.py'))

    @unittest.skipUnless(shutil.which('java'), 'Java runtime/compiler required')
    def test_real_java_exporter_selects_only_complete_current_session(self):
        javac = [shutil.which('javac')] if shutil.which('javac') else [shutil.which('java'), '-m', 'jdk.compiler/com.sun.tools.javac.Main']
        probe = subprocess.run(javac + ['-version'], capture_output=True, text=True)
        if probe.returncode:
            self.skipTest('Java compiler module unavailable')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); classes = root / 'classes'
            compile = subprocess.run(javac + ['--release', '8', '-d', str(classes),
                str(ROOT / 'android/src/com/retroaura/lasrecomp/ShadowCaptureExport.java'),
                str(ROOT / 'tests/ShadowCaptureExportFixture.java')], capture_output=True, text=True)
            self.assertEqual(compile.returncode, 0, compile.stderr)
            run = subprocess.run([shutil.which('java'), '-cp', str(classes),
                'com.retroaura.lasrecomp.ShadowCaptureExportFixture', str(root / 'captures')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertIn('SHADOW_EXPORT_OK latest_only=1 complete_pairs=1', run.stdout)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_native_capture_delays_read_and_owns_all_layers_and_metadata(self):
        surface = subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':src/nx/gpu/vk/surface.c'], text=True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'surf_use_actual.inc').write_text(HELPERS.function(surface, 'void vk_surf_use('))
            command = ['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror', '-I' + str(root),
                       '-I' + str(ROOT / 'tools/zelda-perf'), str(ROOT / 'tests/zelda_shadow_capture_fixture.c'), '-o', str(root / 'capture')]
            build = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(root / 'capture'), d], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertIn('SHADOW_OK off_no_work=1', run.stdout)
            for capture in (1, 2, 3):
                meta = json.loads((root / f'shadow-{capture}.json').read_text())
                report = ANALYZER.analyze_pair(meta, (root / f'shadow-{capture}.depth').read_bytes())
                expected = (0, 1) if capture < 3 else (.25, .75)
                self.assertEqual([x['min'] for x in report['layers']], list(expected))
                self.assertTrue(all(x['constant_finite'] for x in report['layers']))
                self.assertEqual(meta['consumer']['slot'], 7)
                self.assertTrue(report['producer_state']['known'])
                self.assertEqual(report['producer_state']['depth_mode'], 'zero_to_one')
            self.assertEqual(json.loads((root / 'shadow-1.json').read_text())['consumer']['tic'][0], 123)
            failed = subprocess.run([str(root / 'capture'), str(root / 'missing')], capture_output=True, text=True, timeout=30)
            self.assertEqual(failed.returncode, 0, failed.stderr)
            self.assertEqual(failed.stdout.count('"status":"save_failed"'), 3)


if __name__ == '__main__':
    unittest.main()
