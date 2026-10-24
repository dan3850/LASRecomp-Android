"""Byte equivalence and lifetime checks on the actual pinned transfer code."""
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


PATCH = module('transfer_patch', ROOT / 'tools/patch_scarletnx_zelda_transfer.py')
HASH = module('transfer_hash_patch', ROOT / 'tools/patch_scarletnx_zelda_hash_span.py')


def function(text, signature):
    start = text.index(signature)
    first = text[start:].splitlines()[0]
    if first.endswith('}'):
        return first + '\n'
    return text[start:text.index('\n}\n', start) + 3]


def source(name):
    return subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name], text=True)


def patched(name, text):
    for old, new in PATCH.replacements()[name]:
        if text.count(old) != 1:
            raise AssertionError('pinned source mismatch: ' + name)
        text = text.replace(old, new, 1)
    return text


def execute(root, path, *args):
    binary = root / 'test'
    build = subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-ffunction-sections', '-fdata-sections', '-I' + str(root), '-I' + str(SRC / 'src'),
                            '-I' + str(ROOT / 'tools/zelda-perf'), str(path), '-pthread',
                            '-Wl,--gc-sections', '-o', str(binary)], capture_output=True, text=True)
    if build.returncode:
        raise AssertionError(build.stderr)
    for mode in args:
        run = subprocess.run([str(binary)], env={**os.environ, 'SNX_VK_TRANSFER_REUSE': mode},
                             capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise AssertionError(run.stderr + run.stdout)
        yield run.stdout


class TransferTests(unittest.TestCase):
    def test_analyzer_requires_complete_transfer_windows_and_keeps_gauges(self):
        analyzer = module('transfer_analyzer', ROOT / 'tools/analyze_zelda_perf.py')
        rows = [('SNX_PERF_META_V1', {'revision': 'test'}),
                ('SNX_TRANSFER_META_V1', {'enabled': 1})]
        for window in (1, 2):
            rows.append(('SNX_PERF_V1', {'window': window, 'elapsed_s': 5.0 * window, 'duration_ms': 5000}))
            for stream in ('guest_queue', 'render', 'present_enqueue'):
                rows.extend([('SNX_STREAM_V1', {'window': window, 'stream': stream, 'frames': 2, 'samples': 1, 'lost': 0}),
                             ('SNX_FRAMES_V1', {'window': window, 'stream': stream, 'us': [16667]})])
            rows.extend(('SNX_COST_V1', {'window': window, 'metric': str(n), 'calls': 0, 'ms': 0}) for n in range(16))
            rows.append(('SNX_VK_V1', {'window': window, 'draws': 1}))
            rows.append(('SNX_TRANSFER_V1', {'window': window, 'enabled': 1,
                'pool_hits': 7, 'pool_entries': window, 'pool_bytes': 4096 * window,
                'row_calls_before': 12, 'row_calls_after': 1, 'dst_stage_bytes_avoided': 65536}))
        def log(items): return '\n'.join(tag + ' ' + json.dumps(row) for tag, row in items)
        report = analyzer.analyze(log(rows), skip_seconds=0)
        self.assertEqual(report['transfers']['pool_hits'], 14)
        self.assertEqual(report['transfers']['pool_bytes'], 8192)
        self.assertEqual(report['transfers']['pool_entries'], 2)
        self.assertEqual(report['transfers']['row_calls_before'], 24)
        partial = analyzer.analyze(log(rows[:-1]), skip_seconds=0)
        self.assertEqual(partial['windows'], 1)
        with self.assertRaisesRegex(ValueError, 'mode changed'):
            analyzer.analyze(log(rows[:-1] + [('SNX_TRANSFER_V1', {'window': 2, 'enabled': 0})]), skip_seconds=0)

    def test_patch_transactional_idempotent_and_exact_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            original = {}
            for name, pairs in PATCH.replacements().items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                original[name] = '\n/* anchor */\n'.join(old for old, new in pairs)
                path.write_text(original[name])
            PATCH.apply(root)
            once = {name: (root / name).read_bytes() for name in original}
            PATCH.apply(root)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            generated = root / 'src/nx/gpu/vk/snx_transfer_impl.h'
            generated.write_text('unknown edited header')
            with self.assertRaises(ValueError): PATCH.apply(root, True)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in original})
            generated.write_text((ROOT / 'tools/zelda-perf/transfer_impl.h').read_text())
            PATCH.apply(root, True)
            PATCH.apply(root, True)
            self.assertEqual(original, {name: (root / name).read_text() for name in original})
            self.assertFalse(generated.exists())

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_actual_dma_rows_and_fence_retired_pool(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            owned = source('src/nx/gpu/vk/owned.c')
            updated = patched('src/nx/gpu/vk/owned.c', owned)
            for name, signature in [('alloc', 'VkOwnRes* vk_own_res_new('),
                                    ('retain', 'static void res_retain('), ('release', 'static void res_release('),
                                    ('rows', 'void vk_copy_rows(')]:
                (root / (name + '_actual.inc')).write_text(function(updated, signature))
            (root / 'rows_baseline.inc').write_text(function(owned, 'void vk_copy_rows(').replace('vk_copy_rows(', 'baseline_rows(', 1))
            header = patched('src/nx/gpu/vk/vk.h', source('src/nx/gpu/vk/vk.h'))
            start = header.index('typedef struct VkOwnRes {')
            (root / 'resource_actual.inc').write_text(header[start:header.index('} VkOwnRes;', start) + len('} VkOwnRes;')])
            dma = source('src/nx/gpu/vk/dma.c')
            (root / 'dma_helpers_actual.inc').write_text(dma[dma.index('static u64 up('):dma.index('static int dma(')])
            (root / 'dma_baseline.inc').write_text(function(dma, 'static int dma(').replace('static int dma(', 'static int baseline_dma(', 1))
            (root / 'dma_actual.inc').write_text(function(patched('src/nx/gpu/vk/dma.c', dma), 'static int dma(').replace('static int dma(', 'static int optimized_dma(', 1))
            outputs = list(execute(root, ROOT / 'tests/zelda_transfer_fixture.c', '0', '1', 'invalid'))
            for output in outputs:
                self.assertIn('TRANSFER_OK', output)
                self.assertIn('byte_exact=1 deferred_reuse=1 owner_identity=1 bounded_pool=1', output)
            report = json.loads(next(line.split(' ', 1)[1] for line in outputs[1].splitlines() if line.startswith('SNX_TRANSFER_V1 ')))
            self.assertLess(report['row_calls_after'], report['row_calls_before'])
            self.assertGreater(report['dst_stage_bytes_avoided'], 0)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_real_ownership_and_texture_hash_see_new_generation_at_same_pointer(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            header = root / 'nx/memory/own.h'
            header.parent.mkdir(parents=True)
            header.write_text(patched('src/nx/memory/own.h', source('src/nx/memory/own.h')))
            (root / 'own_actual.c').write_text(patched('src/nx/memory/own.c', source('src/nx/memory/own.c')))
            (root / 'snx_settings.h').write_text('struct SnxTestSettings { int log_level; }; extern struct SnxTestSettings g_settings;\n')
            owned = patched('src/nx/gpu/vk/owned.c', source('src/nx/gpu/vk/owned.c'))
            (root / 'peek_actual.inc').write_text(function(owned, 'void vk_guest_peek('))
            (root / 'hash_actual.inc').write_text(function(source('src/nx/gpu/vk/cmd.c'), 'u64 vk_hash('))
            original = function(source('src/nx/gpu/vk/texture.c'), 'static u64 mem_hash(')
            optimized = original.replace(*HASH.PAIRS['src/nx/gpu/vk/texture.c'][1], 1)
            (root / 'hash_baseline.inc').write_text(original.replace('mem_hash(', 'baseline_hash(', 1))
            (root / 'hash_optimized.inc').write_text(optimized.replace('mem_hash(', 'optimized_hash(', 1))
            program = (ROOT / 'tests/zelda_hash_span_fixture.c').read_text()
            helpers = '''static u64 current_identity = 10;
static u64 owner_identity(void* res) { (void)res; return current_identity; }
static u64 snx_transfer_identity(void* res) {
    return g_hooks.identity ? g_hooks.identity(res) : (u64)(uintptr_t)res;
}
'''
            program = program.replace('#include "peek_actual.inc"', helpers + '#include "peek_actual.inc"')
            checks = '''reset_case(); add_owner(0x10800, 32);
    g_hooks.identity = owner_identity;
    u64 h1 = 0, h2 = 0; CHECK(own_hash(0x10000, 4096, &h1));
    u64 t1 = baseline_hash(0x10000, 4096);
    current_identity++;
    CHECK(own_hash(0x10000, 4096, &h2)); CHECK(h1 != h2);
    CHECK(baseline_hash(0x10000, 4096) != t1);
    CHECK(optimized_hash(0x10000, 4096) == baseline_hash(0x10000, 4096));
    g_hooks.identity = NULL;
    reset_case(); CHECK(!munmap'''
            program = program.replace('reset_case(); CHECK(!munmap', checks)
            path = root / 'fixture.c'
            path.write_text(program)
            self.assertIn('HASH_SPAN_OK', list(execute(root, path, '1'))[0])


if __name__ == '__main__':
    unittest.main()
