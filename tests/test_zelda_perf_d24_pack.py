"""Exact D24 transfers: production GLSL, surface qualification, limits and rollback."""
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


PATCH = module('d24_pack_patch', ROOT / 'tools/patch_scarletnx_zelda_d24_pack.py')
HELPERS = module('d24_pack_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')


def source(name):
    return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)


def patched(name):
    text = source(name)
    for old, new in PATCH.replacements().get(name, []):
        if text.count(old) != 1: raise AssertionError('Unknown pinned source: '+name)
        text = text.replace(old, new, 1)
    return text


def prepare_glsl(root):
    folder = root / 'nx/gpu/texture'; folder.mkdir(parents=True, exist_ok=True)
    for name in ('texconv.comp', 'texconv.glsl', 'texconv_modes.glsl'):
        (folder / name).write_text(patched('src/nx/gpu/texture/'+name))
    return folder / 'texconv.comp'


class D24PackTests(unittest.TestCase):
    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('c++'), 'pinned source/C++ required')
    def test_actual_glsl_all_depth_bits_both_layouts_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); prepare_glsl(root)
            build = subprocess.run(['c++', '-std=c++20', '-O2', '-Wall', '-Wextra', '-Werror', '-fwrapv',
                '-I'+d, '-I'+str(SRC / 'tests/glsl'), str(ROOT / 'tests/zelda_d24_glsl_fixture.cpp'),
                '-o', str(root / 'glsl')], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(root / 'glsl')], capture_output=True, text=True, timeout=45)
            self.assertEqual(run.returncode, 0, run.stderr+run.stdout)
            self.assertIn('exhaustive_depths=33554432', run.stdout)
            self.assertIn('old_upload_roundtrip=1', run.stdout)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source/C required')
    def test_production_surface_record_exact_bytes_padding_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); gpu = source('src/nx/gpu/gpu.c')
            (root / 'block_offsets_actual.inc').write_text('\n'.join(HELPERS.function(gpu, n)
                for n in ('static u64 bl_x(', 'static u64 bl_yz(', 'u64 bl_offset(')))
            surface = patched('src/nx/gpu/vk/surface.c')
            (root / 'flush_bytes_actual.inc').write_text(HELPERS.function(surface, 'static u64 flush_bytes('))
            (root / 'pending_actual.inc').write_text(HELPERS.function(surface, 'static u32 rt_pending_over('))
            run = subprocess.run(['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror', '-I'+d,
                '-I'+str(ROOT / 'tools/zelda-perf'), str(ROOT / 'tests/zelda_d24_pack_fixture.c'), '-o', str(root / 'surface')],
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            run = subprocess.run([str(root / 'surface')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr+run.stdout)
            self.assertIn('cpu_policy_unchanged=1 depth_stencil_exact=1 guest_padding_preserved=1', run.stdout)
            self.assertIn('stale_owned_preserved=1 ordered_overlay=1 reuse_invalidated=1', run.stdout)
            rows = [json.loads(l.split(' ', 1)[1]) for l in run.stdout.splitlines() if l.startswith('SNX_D24_PACK_META_V1')]
            self.assertEqual([r['enabled'] for r in rows], [0, 0, 1])

    @unittest.skipUnless((SRC / '.git').exists(), 'pinned source required')
    def test_new_glsl_compiles_and_validates_for_vulkan_11(self):
        compiler = os.environ.get('GLSLANG_VALIDATOR') or shutil.which('glslangValidator')
        validator = os.environ.get('SPIRV_VAL') or shutil.which('spirv-val')
        if not compiler or not validator: self.skipTest('glslangValidator and spirv-val required')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); shader = prepare_glsl(root); out = root / 'new.spv'
            run = subprocess.run([compiler, '-V', '--target-env', 'vulkan1.1', '-g0', '--spirv-val', '-o', str(out), str(shader)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            run = subprocess.run([validator, '--target-env', 'vulkan1.1', str(out)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn((0x534e0014).to_bytes(4, 'little'), out.read_bytes())
            self.assertIn((0x534e0016).to_bytes(4, 'little'), out.read_bytes())

    def test_signed_profile_and_analyzer_complete_windows(self):
        script = (ROOT / 'compilar-zelda-copias-profundidade-termux.sh').read_text()
        gate = script.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        markers = ('SNX_D24_PACK_META_V1','SNX_D24_PACK_V1','SNX_D24_PACK_STATE_V1',
                   '"integration":2,"gpu_overlay_only":1,"cpu_writeback":0,"isolated_work":1',
                   'SNX_EFFECT_DEPTH_PAIR_V1','SNX_DEPTH_RANGE_META_V1','SNX_VB_POOL_META_V1','revision')
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / 'test.apk'
            for missing in ('', 'asset', *markers):
                with zipfile.ZipFile(apk, 'w') as z:
                    z.writestr('assets/licenses/Zelda-D24Copies.txt', 'old' if missing == 'asset' else 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so',' '.join(x for x in markers if x != missing))
                run = subprocess.run([os.sys.executable, '-c', gate, str(apk), 'revision'], capture_output=True, text=True)
                self.assertEqual(run.returncode == 0, missing == '', run.stderr)
        analyzer = module('d24_perf', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'd24'})]
        for w in (1,2):
            rows.append(('SNX_PERF_V1', {'window': w, 'elapsed_s': 5*w, 'duration_ms': 5000}))
            for stream in ('guest_queue','render','present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': w, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': w, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': w, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': w, 'draws': 2}))
        def text(rs): return '\n'.join(k+' '+json.dumps(v) for k,v in rs)
        baseline = analyzer.analyze(text(rows), 0)
        rows += [('SNX_D24_PACK_META_V1', {'enabled': 1})]
        rows += [('SNX_D24_PACK_V1', {'window': w, 'enabled': 1, 'packed': 3, 'pixels': 100, 'failures': 0}) for w in (1,2)]
        result = analyzer.analyze(text(rows),0)
        self.assertEqual(result['streams'], baseline['streams'])
        self.assertEqual(result['packed_depth']['packed'], 6)
        self.assertEqual(analyzer.analyze(text(rows[:-1]),0)['windows'], 1)
        rows[-1][1]['enabled'] = 0
        with self.assertRaisesRegex(ValueError, 'mode changed'): analyzer.analyze(text(rows),0)


if __name__ == '__main__': unittest.main()
