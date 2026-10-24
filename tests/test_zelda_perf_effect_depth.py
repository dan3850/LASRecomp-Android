"""Paired scene-depth evidence: real barriers/lifetime, bounded export, no FPS claims."""
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
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


PATCH = module('effect_depth_patch', ROOT / 'tools/patch_scarletnx_zelda_effect_depth.py')
ANALYZER = module('effect_depth_analyzer', ROOT / 'tools/analyze_zelda_effect_depth.py')
HELPERS = module('effect_depth_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')


def metadata():
    return {'schema': 'SNX_EFFECT_DEPTH_PAIR_V1', 'byte_order': 'little', 'width': 2, 'height': 2,
            'format': 129, 'bytes': 32, 'planes': [
                {'role': 'attachment', 'offset': 0, 'bytes': 16}, {'role': 'sampled', 'offset': 16, 'bytes': 16}]}


class EffectDepthTests(unittest.TestCase):
    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source/C compiler required')
    def test_native_pair_preserves_inputs_and_defers_reads_and_failures(self):
        surface = subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':src/nx/gpu/vk/surface.c'], text=True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'surf_use_actual.inc').write_text(HELPERS.function(surface, 'void vk_surf_use('))
            binary = root / 'effect'
            build = subprocess.run(['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror', '-I'+d,
                '-I'+str(ROOT / 'tools/zelda-perf'), str(ROOT / 'tests/zelda_effect_depth_fixture.c'), '-o', str(binary)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), d], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertIn('EFFECT_DEPTH_OK off_no_work=1 paired=1', run.stdout)
            for i, equal in ((1, 12), (2, 11), (3, 1)):
                m = json.loads((root / f'effect-{i}.json').read_text())
                result = ANALYZER.analyze_pair(m, (root / f'effect-{i}.depth').read_bytes())
                self.assertEqual(result['comparison']['equal'], equal)
                self.assertIsNone(result['comparison']['is_bug'])
                self.assertEqual(m['consumer']['tic'][0], 123)
                self.assertEqual(m['draw_state']['clip_control'], 0x181d)
                self.assertEqual([p['surface'] for p in m['planes']], ['123000', '124000'])
            run = subprocess.run([str(binary), str(root / 'missing')], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout.count('"status":"save_failed"'), 3)

    def test_color_probe_startup_serialization_guards(self):
        color = (ROOT / 'tools/zelda-perf/color_probe.h').read_text()
        self.assertIn('g_vk_present < 180', color)
        self.assertIn('snx_color_probe_pending || snx_effect_depth_pending', color)
        self.assertIn('snx_color_probe_pending = 1;', color)
        self.assertIn('snx_color_probe_pending = 0;', color)
        self.assertIn('stage != snx_color_probe_frames', color)
        self.assertNotIn('snx_color_probe_mask', color)
        render_patch = PATCH.replacements()['src/nx/gpu/vk/render.c']
        self.assertIn('!snx_color_probe_pending', render_patch[1][1])
        self.assertIn('snx_color_probe_after_draw(fs, rt[0], writes);', render_patch[2][1])

    def test_parser_checks_planar_layout_masks_d24_and_bounds_archive(self):
        raw = struct.pack('<8I', *([0xff800000]*4 + [0x11800000]*4))
        result = ANALYZER.analyze_pair(metadata(), raw)
        self.assertEqual(result['comparison']['equal'], 4)
        self.assertEqual(result['producer_relationship'], 'unproven')
        for bad in ({**metadata(), 'bytes': 31}, {**metadata(), 'format': 37},
                    {**metadata(), 'planes': [{'role': 'attachment', 'offset': 1, 'bytes': 16}, metadata()['planes'][1]]}):
            with self.assertRaises(ValueError): ANALYZER.analyze_pair(bad, raw)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'e.zip'; entry = 'effects/0000000000000001/effect-1'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr(entry+'.json', json.dumps(metadata())); z.writestr(entry+'.depth', raw)
                z.writestr('../../ignored', 'ignored')
            out = Path(d) / 'previews'
            self.assertEqual(len(ANALYZER.analyze_archive(path, out)), 1)
            self.assertEqual(len(list(out.glob('*.pgm'))), 4)
            self.assertFalse((Path(d).parent/'ignored').exists())
            with zipfile.ZipFile(path, 'w') as z: z.writestr(entry+'.json', json.dumps(metadata()))
            with self.assertRaisesRegex(ValueError, 'Missing'): ANALYZER.analyze_archive(path)
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr(entry+'.json', '{}'); z.writestr(entry.replace('0001', '0002')+'.json', '{}')
            with self.assertRaisesRegex(ValueError, 'one effect session'): ANALYZER.analyze_archive(path)

    def test_patch_preflight_does_not_write_partial_unknown_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, pairs in PATCH.replacements().items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('\n'.join(x[0] for x in pairs))
            bad = root / 'src/nx/gpu/vk/renderer.c'; bad.write_text('unknown')
            before = {p: p.read_bytes() for p in root.rglob('*.c')}
            h = root / 'src/nx/gpu/vk/vk.h'; old = h.read_bytes()
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*.c')})
            self.assertEqual(h.read_bytes(), old)
            self.assertFalse((root / 'src/nx/gpu/vk/snx_effect_depth.h').exists())

    def test_profile_gate_and_launcher_default_and_fps_exclusion(self):
        script = (ROOT / 'compilar-zelda-efeitos-termux.sh').read_text()
        gate = script.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        markers = ('SNX_EFFECT_DEPTH_CAPTURE_V1', 'SNX_EFFECT_DEPTH_PAIR_V1', 'SNX_COLOR_PROBE_V1', 'SNX_DEPTH_RANGE_META_V1', 'SNX_VB_POOL_META_V1', 'revision')
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / 'test.apk'
            for missing in ('', 'asset', *markers):
                with zipfile.ZipFile(apk, 'w') as z:
                    z.writestr('assets/licenses/Zelda-EffectDepth.txt', 'old' if missing == 'asset' else 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                r = subprocess.run([os.sys.executable, '-c', gate, str(apk), 'revision'], capture_output=True, text=True)
                self.assertEqual(r.returncode == 0, missing == '', r.stderr)
        boot = (ROOT / 'android/src/com/retroaura/lasrecomp/CastlevaniaSnxBootActivity.java').read_text()
        game = (ROOT / 'android/src/com/retroaura/lasrecomp/MarioSnxGameActivity.java').read_text()
        self.assertIn('getBoolean("zelda_effect_depth_v1", false)', boot)
        self.assertIn('effectDepthDir == null ? "" : effectDepthDir', game)
        perf = module('effect_perf', ROOT / 'tools/analyze_zelda_perf.py')
        with self.assertRaisesRegex(ValueError, 'not an FPS comparison'):
            perf.analyze('SNX_PERF_META_V1 {"revision":"effect"}\nSNX_EFFECT_DEPTH_CAPTURE_V1 {"status":"armed"}')


if __name__ == '__main__': unittest.main()
