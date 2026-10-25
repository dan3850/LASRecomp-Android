"""Actual nxnative compute adapter/cache, with synthetic programs only."""
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
REFLECTION = {
    'abi': 1, 'stage': 'cs', 'notes': [], 'textures': [], 'images': [],
    'cbufs': [{'binding': 5, 'slot': 0}, {'binding': 7, 'slot': 4}],
    'sbufs': [
        {'binding': 1, 'slot': 0, 'cb_slot': 0, 'cb_offset': 168, 'flags': 0},
        {'binding': 2, 'slot': 1, 'cb_slot': 0, 'cb_offset': 196, 'flags': 1},
        {'binding': 3, 'slot': 2, 'cb_slot': 0, 'cb_offset': 200, 'flags': 1},
    ],
}


def prepare(out):
    header = out / 'nx/gpu/vk'
    header.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'tools/zelda-perf/nx_compute_adapter.h', header / 'snx_nx_compute_adapter.h')
    shader = out / 'synthetic.spv'
    subprocess.run(['glslangValidator', '-V', '--target-env', 'vulkan1.0',
                    str(ROOT / 'tests/zelda_nx_compute.comp'), '-o', str(shader)],
                   check=True, capture_output=True, text=True)
    reflection = out / 'synthetic.json'
    reflection.write_text(json.dumps(REFLECTION))
    return shader, reflection


@unittest.skipUnless(shutil.which('cc') and shutil.which('glslangValidator') and shutil.which('spirv-val')
                     and (SRC / '.git').exists(), 'pinned source and actual compiler/SPIR-V tools required')
class NxComputeTests(unittest.TestCase):
    def test_actual_compute_pipeline_c1_and_driver_rejection_fallback(self):
        spec = importlib.util.spec_from_file_location('nxpatch', ROOT / 'tools/patch_scarletnx_zelda_nx_compute.py')
        patch = importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)
        source = subprocess.check_output(['git', '-C', str(SRC), 'show',
            '34853eeae5af132e320adbb0193f13344085bf89:src/nx/gpu/vk/compute.c'], text=True)
        for old, new in patch.replacements()['src/nx/gpu/vk/compute.c']:
            self.assertEqual(source.count(old), 1)
            source = source.replace(old, new, 1)
        structs = source[source.index('typedef struct CsPipe {'):source.index('/* the arena:')]
        start = source.index('typedef struct {\n    u64 tex_int, tex_sint;')
        end = source.index('\n}\n', source.index('static CsPipe* cs_pipe(', start)) + 3
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / 'nx_cs_pipe_actual.inc').write_text(structs + source[start:end])
            binary = out / 'pipe'
            r = subprocess.run(['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror',
                '-I' + str(out), '-I' + str(SRC / 'src'),
                str(ROOT / 'tests/zelda_nx_compute_pipe_fixture.c'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('Vulkan module/pipeline rejection passed', r.stdout)

    def test_actual_adapter_raw_abi_cache_invalidation_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            shader, reflection = prepare(out)
            cache = out / 'cache'; cache.mkdir()
            legacy = out / 'vk_pipelines.bin'; legacy.write_bytes(b'approved legacy cache')
            binary = out / 'test'
            result = subprocess.run(['cc', '-std=gnu11', '-D_GNU_SOURCE', '-O1', '-Wall', '-Wextra', '-Werror',
                '-I' + str(out), '-I' + str(SRC / 'src'), '-I' + str(ROOT / 'tools/zelda-perf'),
                str(ROOT / 'tests/zelda_nx_compute_fixture.c'),
                str(SRC / 'src/nx/runtime/driver/hactool/cJSON.c'), '-ldl', '-lm', '-o', str(binary)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            adapted = out / 'adapted.spv'
            result = subprocess.run([str(binary), str(shader), str(reflection), str(cache), str(adapted)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('C1/code/launch/chain invalidation', result.stdout)
            restarted = subprocess.run([str(binary), str(shader), str(reflection), str(cache), str(adapted), 'warm'],
                                       capture_output=True, text=True)
            self.assertEqual(restarted.returncode, 0, restarted.stderr)
            self.assertIn('disk entry reused without calling translator', restarted.stdout)
            result = subprocess.run(['spirv-val', '--target-env', 'vulkan1.3', str(adapted)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(legacy.read_bytes(), b'approved legacy cache')

    def test_patch_rejects_changed_source_without_partial_writes(self):
        spec = importlib.util.spec_from_file_location('nxpatch', ROOT / 'tools/patch_scarletnx_zelda_nx_compute.py')
        patch = importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d); before = {}
            for name, pairs in patch.replacements().items():
                path = out / name; path.parent.mkdir(parents=True, exist_ok=True)
                before[name] = '\n/* anchor */\n'.join(old for old, _ in pairs)
                path.write_text(before[name])
            path = out / 'src/nx/gpu/vk/compute.c'
            path.write_text(path.read_text().replace('    u32* spv = vk_translate_spirv(', 'CHANGED('))
            before['src/nx/gpu/vk/compute.c'] = path.read_text()
            with self.assertRaisesRegex(ValueError, 'no changes'):
                patch.apply(out)
            self.assertEqual(before, {name: (out / name).read_text() for name in before})


if __name__ == '__main__':
    unittest.main()
