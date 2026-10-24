"""Native translator, cache-compatible SPIR-V proof and strict buffer bytes."""
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


PATCH = module('ub_extent_patch', ROOT / 'tools/patch_scarletnx_zelda_ub_extent.py')
UNIFORM = module('ux_uniform_test_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')


class UniformExtentTests(unittest.TestCase):
    def test_atomic_preflight_idempotency_and_byte_exact_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            original = {}
            for name, pairs in PATCH.replacements().items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True)
                original[name] = '\n/* anchor */\n'.join(old for old, new in pairs)
                p.write_text(original[name])
            PATCH.apply(root)
            once = {name: (root / name).read_bytes() for name in original}
            PATCH.apply(root)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            header = root / 'src/nx/gpu/vk/snx_ub_extent.h'
            good = header.read_text(); header.write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root, True)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            header.write_text(good)
            PATCH.apply(root, True); PATCH.apply(root, True)
            self.assertEqual(original, {name: (root / name).read_text() for name in original})
            (root / 'src/nx/gpu/vk/renderer.c').write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/pipeline.c').read_text(), original['src/nx/gpu/vk/pipeline.c'])
            self.assertFalse(header.exists())

    def test_analyzer_legacy_and_complete_matching_extent_windows(self):
        analyzer = module('ux_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'extent-test'})]
        for w in (1, 2):
            rows.append(('SNX_PERF_V1', {'window': w, 'elapsed_s': 5 * w, 'duration_ms': 5000}))
            for stream in ('guest_queue', 'render', 'present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': w, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': w, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': w, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': w, 'draws': 2}))
        def log(items): return '\n'.join(tag + ' ' + json.dumps(row) for tag, row in items)
        legacy = analyzer.analyze(log(rows), 0)
        self.assertNotIn('uniform_extent', legacy)
        meta = ('SNX_UB_EXTENT_META_V1', {'enabled': 1, 'spirv_proof': 1, 'shader_unchanged': 1})
        summaries = [('SNX_UB_EXTENT_V1', {'window': w, 'enabled': 1, 'bindings': 5,
                     'reduced_bindings': 2, 'requested_bytes': 65536, 'bound_bytes': 1024}) for w in (1, 2)]
        result = analyzer.analyze(log(rows + [meta] + summaries), 0)
        self.assertEqual(result['streams'], legacy['streams'])
        self.assertEqual(result['uniform_extent']['reduced_bindings'], 4)
        self.assertEqual(result['uniform_extent']['bound_bytes'], 2048)
        self.assertEqual(analyzer.analyze(log(rows + [meta, summaries[0]]), 0)['windows'], 1)
        self.assertEqual(analyzer.analyze(log(rows + [meta] + summaries + [summaries[1]]), 0)['windows'], 1)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows + [meta, summaries[0], (summaries[1][0], {**summaries[1][1], 'enabled': 0})]), 0)

    def test_signed_extent_profile_requires_all_current_assets_and_markers(self):
        import zipfile
        wrapper = (ROOT / 'compilar-zelda-uniformes-alcance-termux.sh').read_text()
        gate = wrapper.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        assets = ('Zelda-NXNative.txt', 'Zelda-Uniforms.txt', 'Zelda-Clears.txt', 'Zelda-UniformExtent.txt')
        markers = ('SNX_UB_EXTENT_META_V1', 'SNX_CLEAR_LOAD_META_V1', 'SNX_UNIFORM_META_V1', 'SNX_TRANSFER_META_V1', 'revision')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.apk'
            for missing in ('', *assets, *markers):
                with zipfile.ZipFile(path, 'w') as z:
                    for name in assets:
                        if name != missing: z.writestr('assets/licenses/' + name, 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so', ' '.join(x for x in markers if x != missing))
                result = subprocess.run([shutil.which('python3') or 'python', '-c', gate, str(path), 'revision'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, missing == '', result.stderr)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_actual_native_modules_proven_extents_and_strict_snapshot_bytes(self):
        def source(name):
            return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); tree = root / 'source'
            for directory in ('src/nx/gpu/shader', 'src/common/cpu/aarch64',
                              'src/common/runtime/interface.h', 'tools/shaderdec'):
                names = subprocess.check_output(['git', '-C', str(SRC), 'ls-tree', '-r', '--name-only', PIN, '--', directory], text=True)
                for name in names.splitlines():
                    p = tree / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(source(name))
            # Use the same tested Bionic O_SYNC shield as the existing regressions.
            shader_tests = module('ux_shader_test_helpers', ROOT / 'tests/test_zelda_perf_shader.py')
            translator = tree / 'src/nx/gpu/shader/translator.h'
            translator.write_text(translator.read_text().replace('#include "maxwell_opcodes.h"', shader_tests.HOST_OPCODE_INCLUDE, 1))
            subprocess.run(['cc', '-O0', str(tree / 'tools/shaderdec/shaderdec.c'), '-o', str(root / 'shaderdec')], check=True, capture_output=True)
            subprocess.run([str(root / 'shaderdec'), '--enum', str(root / 'maxwell_opcodes.h'), '--decoder', str(root / 'maxwell_decode.inc'),
                            str(tree / 'src/nx/gpu/shader/maxwell_opcodes.def')], check=True, capture_output=True)
            original = source('src/nx/gpu/vk/buffer.c')
            changed = UNIFORM.patched('src/nx/gpu/vk/buffer.c', original)
            start = original.index('typedef struct Vb {')
            (root / 'vb_actual.inc').write_text(original[start:original.index('} Vb;', start) + len('} Vb;')])
            for name, signature in [('own_link', 'static void own_link('), ('own_unlink', 'static void own_unlink('),
                                    ('use', 'static void use('), ('drop_own', 'static void drop_own('),
                                    ('make_own', 'static int make_own('), ('guest_bytes', 'static const u8* guest_bytes('),
                                    ('copy', 'int vk_buf_copy(')]:
                (root / (name + '_actual.inc')).write_text(UNIFORM.function(original, signature))
            (root / 'hash_actual.inc').write_text(UNIFORM.function(source('src/nx/gpu/vk/cmd.c'), 'u64 vk_hash('))
            (root / 'baseline_actual.inc').write_text(UNIFORM.function(original, UNIFORM.PATCH.GET_OLD).replace('buf_get(', 'baseline_get(', 1))
            (root / 'optimized_actual.inc').write_text(UNIFORM.function(changed, UNIFORM.PATCH.GET_NEW))
            (root / 'wrappers_actual.inc').write_text('\n'.join(UNIFORM.function(changed, s) for s in
                                                        ('int vk_buf_get(', 'int vk_buf_get_strict(', 'int vk_buf_get_uniform(')))
            render = source('src/nx/gpu/vk/render.c')
            (root / 'cb_baseline.inc').write_text(UNIFORM.function(render, 'static int cb_get(').replace('cb_get(', 'baseline_cb(', 1).replace('vk_buf_get_strict(', 'baseline_strict(', 1))
            (root / 'cb_actual.inc').write_text(UNIFORM.function(UNIFORM.patched('src/nx/gpu/vk/render.c', render), 'static int cb_get('))
            for old, new in PATCH.replacements()['src/nx/gpu/vk/render.c']:
                self.assertEqual(render.count(old), 1); render = render.replace(old, new, 1)
            start = render.index('        u32 sz = ch->cbind_size[stage][i];', render.index('static VkDescriptorSet stage_set('))
            sizing = render[start:render.index('        VkBuffer b;', start)]
            (root / 'binding_size_actual.inc').write_text('static u32 binding_size(const GpuChannel* ch, int stage, int i, const VkSh* s) {\n' + sizing + '    return sz;\n}\n')
            vk = source('src/nx/gpu/vk/vk.h')
            for old, new in PATCH.replacements()['src/nx/gpu/vk/vk.h']:
                self.assertEqual(vk.count(old), 1); vk = vk.replace(old, new, 1)
            end = vk.index('} VkCbReads;') + len('} VkCbReads;')
            start = vk.rfind('typedef struct {', 0, vk.index('} VkCbRead;'))
            cb_types = vk[start:end]
            start = vk.index('typedef struct VkSh {'); vk_end = vk.index('} VkSh;', start) + len('} VkSh;')
            pf = source('src/nx/gpu/vk/pipeline_file.h'); end = pf.index('} PfShader;') + len('} PfShader;')
            start_pf = pf.rfind('typedef struct {', 0, end)
            (root / 'cache_types_actual.inc').write_text(cb_types + '\n' + vk[start:vk_end] + '\n' + pf[start_pf:end])
            pipeline = source('src/nx/gpu/vk/pipeline.c')
            (root / 'mod_bits_actual.inc').write_text(UNIFORM.function(pipeline, 'static u64 mod_bits('))
            # Use the exact cache-loader patch; module creation is instrumented.
            old, new = PATCH.replacements()['src/nx/gpu/vk/pipeline.c'][-1]
            self.assertEqual(pipeline.count(old), 1); pipeline = pipeline.replace(old, new, 1)
            (root / 'cache_load_actual.inc').write_text(UNIFORM.function(pipeline, 'static u64 pf_load_shader('))
            binary = root / 'test'
            command = ['cc', '-std=gnu11', '-O1', '-I' + str(root), '-I' + str(tree / 'src'),
                       '-I' + str(ROOT / 'tests'), '-I' + str(ROOT / 'tools/zelda-perf'), str(ROOT / 'tests/zelda_ub_extent_fixture.c')]
            command += [str(tree / 'src/nx/gpu/shader' / s) for s in
                        ('shader.c', 'decode.c', 'corpus.c', 'spirv_translate.c', 'spirv_compute.c', 'spirv_emit.c')]
            build = subprocess.run(command + ['-lm', '-pthread', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode in ('0', '1', 'invalid'):
                run = subprocess.run([str(binary), str(root)], env={**os.environ, 'SNX_VK_UNIFORM_STREAM': '1', 'SNX_VK_UB_EXTENT': mode},
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                self.assertIn('UB_EXTENT_OK native_programs=61 shader_unchanged=1 strict_bytes=1 cache_reopen=1 old_draws_immutable=1', run.stdout)
                data = json.loads(next(line.split(' ', 1)[1] for line in run.stdout.splitlines() if line.startswith('SNX_UB_EXTENT_V1 ')))
                self.assertEqual(data['enabled'], int(mode == '1'))
                if mode == '1':
                    self.assertGreater(data['reduced_bindings'], 0)
                    self.assertLess(data['bound_bytes'], data['requested_bytes'])
                else:
                    self.assertTrue(all(v == 0 for k, v in data.items() if k not in ('window', 'enabled')))
            validator = os.environ.get('SPIRV_VAL') or shutil.which('spirv-val')
            if validator:
                for path in root.glob('ldc-*.spv'):
                    run = subprocess.run([validator, '--target-env', 'vulkan1.3', str(path)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
