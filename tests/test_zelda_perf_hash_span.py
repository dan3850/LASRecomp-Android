"""Range-qualified reads with real pinned ownership, peek and hash functions."""
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


def load_patch():
    spec = importlib.util.spec_from_file_location('hash_span_patch', ROOT / 'tools/patch_scarletnx_zelda_hash_span.py')
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    return patch


def function(text, signature):
    start = text.index(signature)
    return text[start:text.index('\n}\n', start) + 3]


class HashSpanTests(unittest.TestCase):
    def test_analyzer_checks_complete_hash_span_windows_and_keeps_legacy_logs(self):
        spec = importlib.util.spec_from_file_location('hash_span_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        analyzer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(analyzer)
        rows = [('SNX_PERF_META_V1', {'revision': 'synthetic'}),
                ('SNX_PERF_V1', {'window': 1, 'elapsed_s': 5.0, 'duration_ms': 5000})]
        for stream in ('guest_queue', 'render', 'present_enqueue'):
            rows.extend([('SNX_STREAM_V1', {'window': 1, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                         ('SNX_FRAMES_V1', {'window': 1, 'stream': stream, 'us': [16667]})])
        rows.extend(('SNX_COST_V1', {'window': 1, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
        rows.append(('SNX_VK_V1', {'window': 1, 'draws': 1}))
        def log(items): return '\n'.join(tag + ' ' + json.dumps(row) for tag, row in items)
        legacy = analyzer.analyze(log(rows), skip_seconds=0)
        self.assertNotIn('hash_span', legacy)
        meta = ('SNX_HASH_SPAN_META_V1', {'enabled': 1, 'all_bytes_checked': 1})
        summary = ('SNX_HASH_SPAN_V1', {'window': 1, 'enabled': 1, 'checks': 3, 'direct_calls': 1,
                                     'direct_bytes': 65536, 'owned_fallback': 1, 'noncontiguous_fallback': 1})
        report = analyzer.analyze(log(rows + [meta, summary]), skip_seconds=0)
        self.assertEqual(report['streams'], legacy['streams'])
        self.assertEqual(report['hash_span']['direct_bytes'], 65536)
        self.assertEqual(report['metadata']['hash_span']['enabled'], 1)
        with self.assertRaisesRegex(ValueError, 'No complete windows'):
            analyzer.analyze(log(rows + [meta]), skip_seconds=0)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows + [meta, (summary[0], {**summary[1], 'enabled': 0})]), skip_seconds=0)

    def test_patch_is_transactional_idempotent_and_reversible(self):
        patch = load_patch()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            before = {}
            for name, pairs in patch.PAIRS.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                before[name] = '\n/* anchor */\n'.join(old for old, new in pairs)
                path.write_text(before[name])
            patch.apply(root)
            once = {name: (root / name).read_text() for name in before}
            patch.apply(root)
            self.assertEqual(once, {name: (root / name).read_text() for name in before})
            patch.apply(root, True)
            patch.apply(root, True)
            self.assertEqual(before, {name: (root / name).read_text() for name in before})
            header = root / 'src/nx/gpu/vk/snx_hash_span.h'
            self.assertFalse(header.exists())
            last = root / 'src/nx/runtime/snx_perf.h'
            last.write_text('unknown source')
            with self.assertRaises(ValueError): patch.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/texture.c').read_text(), before['src/nx/gpu/vk/texture.c'])
            self.assertFalse(header.exists())

    @unittest.skipUnless(shutil.which('cc') and (SRC / '.git').exists(), 'C compiler and pinned source required')
    def test_real_hash_equivalence_protected_owner_pages_and_pending_writes(self):
        def source(name):
            return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)
        patch = load_patch()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'own_actual.c').write_text(source('src/nx/memory/own.c'))
            (root / 'snx_settings.h').write_text('struct SnxTestSettings { int log_level; }; extern struct SnxTestSettings g_settings;\n')
            (root / 'peek_actual.inc').write_text(function(source('src/nx/gpu/vk/owned.c'), 'void vk_guest_peek('))
            (root / 'hash_actual.inc').write_text(function(source('src/nx/gpu/vk/cmd.c'), 'u64 vk_hash('))
            original = function(source('src/nx/gpu/vk/texture.c'), 'static u64 mem_hash(')
            optimized = original.replace(*patch.PAIRS['src/nx/gpu/vk/texture.c'][1], 1)
            self.assertNotEqual(original, optimized)
            (root / 'hash_baseline.inc').write_text(original.replace('mem_hash(', 'baseline_hash(', 1))
            (root / 'hash_optimized.inc').write_text(optimized.replace('mem_hash(', 'optimized_hash(', 1))
            binary = root / 'test'
            command = ['cc', '-std=gnu11', '-O2', '-ffunction-sections', '-fdata-sections', '-I' + str(root),
                       '-I' + str(SRC / 'src'), '-I' + str(ROOT / 'tools/zelda-perf'),
                       str(ROOT / 'tests/zelda_hash_span_fixture.c'), '-Wl,--gc-sections', '-pthread', '-o', str(binary)]
            build = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('HASH_SPAN_OK', run.stdout)
            self.assertIn('all_bytes_hashed=1 gpu_landings=0', run.stdout)


if __name__ == '__main__':
    unittest.main()
