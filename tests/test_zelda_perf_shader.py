"""Execute the real pinned translator on synthetic FSWZADD programs.

The small evaluator stops at the straight-line fragment output. It implements
only the opcodes exercised here and rejects everything else; it is not a GPU
or a general SPIR-V emulator. Captured game programs are never test fixtures.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get('SCARLETNX_TEST_SRC', ROOT.parent / 'ScarletNX-audit'))
PIN = '34853eeae5af132e320adbb0193f13344085bf89'
# Only the disposable host-test copy uses this shim. Bionic/Termux headers
# can expose the POSIX file-open flag before Maxwell's opcode enum is read.
# Include fcntl first so a later include cannot reintroduce that macro.
HOST_OPCODE_INCLUDE = '''#include <fcntl.h>
#ifdef O_SYNC
#undef O_SYNC
#endif
#include "maxwell_opcodes.h"'''


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def f32(bits):
    return struct.unpack('<f', struct.pack('<I', bits))[0]


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def maxwell_reference(mask, pair):
    axis = 2 if mask in (0xa5, 0x5a) else 1
    rhs = [1.0, 4.0, 11.0, 21.0] if pair else [-7.5] * 4
    lhs = [rhs[k ^ axis] for k in range(4)] if pair else [13.25] * 4
    x_lut, y_lut = (1, -1, 1, 0), (1, 1, -1, 1)
    return [lhs[k] * x_lut[(mask >> (k * 2)) & 3] + rhs[k] * y_lut[(mask >> (k * 2)) & 3] for k in range(4)]


def fragment_red(path, first_lane=0):
    data = path.read_bytes()
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    assert words[0] == 0x07230203
    instructions = []
    at = 5
    while at < len(words):
        n, op = words[at] >> 16, words[at] & 65535
        assert n and at + n <= len(words)
        instructions.append((op, words[at + 1:at + n]))
        at += n
    locations, builtins, storage = {}, {}, {}
    for op, p in instructions:
        if op == 71 and p[1] == 30: locations[p[0]] = p[2]
        if op == 71 and p[1] == 11: builtins[p[0]] = p[2]
        if op == 59: storage[p[1]] = p[2]
    values, memory, pointers = {}, {}, {}
    input_red = [bits(x) for x in (1.0, 4.0, 11.0, 21.0)]
    for op, p in instructions:
        if op in (41, 42): values[p[1]] = [int(op == 41)] * 4
        elif op == 43: values[p[1]] = [p[2]] * 4
        elif op == 44: values[p[1]] = [tuple(values[x][k] for x in p[2:]) for k in range(4)]
        elif op == 59:
            ident = p[1]
            pointers[ident] = (ident, ())
            if builtins.get(ident) == 41: memory[ident] = list(range(first_lane, first_lane + 4))
            elif builtins.get(ident) == 15: memory[ident] = [(0, 0, 0, bits(1.0))] * 4
            elif storage[ident] == 1 and locations.get(ident) == 0:
                memory[ident] = [(x, 0, 0, 0) for x in input_red]
            else: memory[ident] = list(values[p[3]]) if len(p) > 3 else [0] * 4
        elif op == 61:
            root, indices = pointers[p[2]]
            out = list(memory[root])
            for index in indices: out = [v[index] for v in out]
            values[p[1]] = out
        elif op == 62:
            root, indices = pointers[p[0]]
            assert not indices
            memory[root] = list(values[p[1]])
            if storage[root] == 3 and locations.get(root) == 0:
                return [f32(v[0]) for v in memory[root]]
        elif op == 65:
            root, indices = pointers[p[2]]
            extra = tuple(values[x][0] for x in p[3:])
            assert all(values[x] == [values[x][0]] * 4 for x in p[3:])
            pointers[p[1]] = (root, indices + extra)
        elif op == 80: values[p[1]] = [tuple(values[x][k] for x in p[2:]) for k in range(4)]
        elif op == 81: values[p[1]] = [v[p[3]] for v in values[p[2]]]
        elif op == 124: values[p[1]] = list(values[p[2]])
        elif op == 127: values[p[1]] = [x ^ 0x80000000 for x in values[p[2]]]
        elif op in (129, 133):
            values[p[1]] = [bits(f32(x) + f32(y) if op == 129 else f32(x) * f32(y)) for x, y in zip(values[p[2]], values[p[3]])]
        elif op in (194, 197, 198, 199, 200, 170, 169):
            a = values[p[2]]
            b = values[p[3]] if len(p) > 3 else [0] * 4
            if op == 194: out = [x >> y for x, y in zip(a, b)]
            elif op == 197: out = [x | y for x, y in zip(a, b)]
            elif op == 198: out = [x ^ y for x, y in zip(a, b)]
            elif op == 199: out = [x & y for x, y in zip(a, b)]
            elif op == 200: out = [~x & 0xffffffff for x in a]
            elif op == 170: out = [int(x == y) for x, y in zip(a, b)]
            else: out = [b[k] if a[k] else values[p[4]][k] for k in range(4)]
            values[p[1]] = out
        elif op in (207, 208):
            v = [f32(x) for x in values[p[2]]]
            out = [v[1]-v[0], v[1]-v[0], v[3]-v[2], v[3]-v[2]] if op == 207 else [v[2]-v[0], v[3]-v[1], v[2]-v[0], v[3]-v[1]]
            values[p[1]] = list(map(bits, out))
        elif op == 345:  # OpGroupNonUniformShuffle (the synthetic BFLY pair)
            values[p[1]] = [values[p[3]][lane - first_lane] for lane in values[p[4]]]
        elif op == 176: values[p[1]] = [int(x < y) for x, y in zip(values[p[2]], values[p[3]])]
        elif op == 168: values[p[1]] = [int(not x) for x in values[p[2]]]
        elif op in {10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23, 28, 30, 32, 33, 54, 71, 72, 248}:
            pass  # declarations and the single function's initial label
        else: raise AssertionError(f'unhandled SPIR-V opcode before fragment output: {op}')
    raise AssertionError('no fragment output')


class ShaderPatchTests(unittest.TestCase):
    def test_signed_apk_gate_requires_the_requested_repair_mode(self):
        import zipfile
        builder = (ROOT / 'compilar-zelda-fps-audit-termux.sh').read_text()
        gate = builder.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        revision = 'synthetic-revision'
        markers = b'SNX_PERF_META_V1 SNX_GFX_BIND_V1 SNX_SHADER_CAPTURE_V1 SNX_RYU_CACHE_V1 SNX_KNOWN_COMPLETE_V1 SNX_HASH_SPAN_META_V1 SNX_TRANSFER_META_V1 SNX_UNIFORM_META_V1 SNX_CLEAR_LOAD_META_V1 SNX_UB_EXTENT_META_V1 synthetic-revision'
        with tempfile.TemporaryDirectory() as d:
            archive = Path(d) / 'synthetic.apk'
            for fixed in (False, True):
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('lib/arm64-v8a/libscarletnx.so', markers + (b' SNX_FSWZADD_V1' if fixed else b''))
                    z.writestr('assets/licenses/Zelda-PERF.txt', revision)
                for requested in (False, True):
                    run = subprocess.run([os.sys.executable, '-c', gate, str(archive), revision, str(int(requested))], capture_output=True, text=True)
                    self.assertEqual(run.returncode == 0, requested == fixed, run.stderr)

    def test_atomic_cache_and_shader_pair_refuses_unknown_or_partial_source(self):
        patch = load('zelda_fswz_atomic', ROOT / 'tools/patch_scarletnx_zelda_fswz.py')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shader = root / 'src/nx/gpu/shader/spirv_translate.c'
            cache = root / 'src/nx/gpu/vk/pipeline.c'
            shader.parent.mkdir(parents=True)
            cache.parent.mkdir(parents=True)
            original = '\n'.join(old for old, new in patch.SHADER_PAIRS)
            shader.write_text(original)
            cache.write_text('unknown upstream source')
            with self.assertRaises(ValueError): patch.apply(root)
            self.assertEqual(shader.read_text(), original)
            cache.write_text(patch.CACHE_PAIRS[0][0])
            patch.apply(root)
            patched = shader.read_text(), cache.read_text()
            patch.apply(root)
            self.assertEqual(patched, (shader.read_text(), cache.read_text()))
            shader.write_text(original)
            with self.assertRaisesRegex(ValueError, 'Partial'): patch.apply(root)
            self.assertEqual(shader.read_text(), original)
            self.assertEqual(cache.read_text(), patched[1])
            shader.write_text(patched[0])
            patch.apply(root, True)
            patch.apply(root, True)
            self.assertEqual(shader.read_text(), original)
            self.assertEqual(cache.read_text(), patch.CACHE_PAIRS[0][0])


@unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
class ShaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.source = cls.work / 'source'
        for directory in ('src/nx/gpu/shader', 'src/common/cpu/aarch64', 'src/common/runtime/interface.h', 'tools/shaderdec'):
            names = subprocess.check_output(['git', '-C', str(SRC), 'ls-tree', '-r', '--name-only', PIN, '--', directory], text=True)
            for name in names.splitlines():
                target = cls.source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name]))
        translator = cls.source / 'src/nx/gpu/shader/translator.h'
        cls.original_translator = translator.read_text()
        anchor = '#include "maxwell_opcodes.h"'
        if cls.original_translator.count(anchor) != 1:
            raise AssertionError('unknown pinned translator opcode include')
        translator.write_text(cls.original_translator.replace(anchor, HOST_OPCODE_INCLUDE, 1))
        cls.shader = cls.source / 'src/nx/gpu/shader/spirv_translate.c'
        # Match the actual shared builder's pre-existing diagnostics and D7 patch.
        bindless = load('bindless_for_fswz', ROOT / 'tools/patch_scarletnx_bindless_diag.py')
        d7 = load('d7_for_fswz', ROOT / 'tools/patch_scarletnx_fswzadd.py')
        cls.shader.write_text(d7.apply(bindless.transform(cls.shader.read_text())))
        cls.before = cls.shader.read_text()
        subprocess.run(['cc', '-O0', str(cls.source / 'tools/shaderdec/shaderdec.c'), '-o', str(cls.work / 'shaderdec')], check=True, capture_output=True)
        subprocess.run([str(cls.work / 'shaderdec'), '--enum', str(cls.work / 'maxwell_opcodes.h'), '--decoder', str(cls.work / 'maxwell_decode.inc'), str(cls.source / 'src/nx/gpu/shader/maxwell_opcodes.def')], check=True, capture_output=True)

    def compile(self, name):
        binary = self.work / name
        sources = ['shader.c', 'decode.c', 'corpus.c', 'spirv_translate.c', 'spirv_compute.c', 'spirv_emit.c']
        command = ['cc', '-std=gnu11', '-O0', '-I' + str(self.source / 'src'), '-I' + str(self.work), str(ROOT / 'tests/zelda_fswz_fixture.c')]
        command.extend(str(self.source / 'src/nx/gpu/shader' / x) for x in sources)
        result = subprocess.run(command + ['-lm', '-pthread', '-o', str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return binary

    def test_posix_sync_collision_reproduces_then_real_decoder_preserves_opcode(self):
        # Force the phone's failing include order even on a glibc host.
        probe = self.work / 'sync_probe.c'
        probe.write_text('''#include <fcntl.h>
static const int posix_sync_flag = O_SYNC;
#include "nx/gpu/shader/translator.h"
#include <assert.h>
#ifdef O_SYNC
#error POSIX macro still hides the Maxwell opcode
#endif
int main(void) {
    const Op* op = decode(0xf0f800000000000full);
    assert(posix_sync_flag > 0);
    assert(op && op->id == O_SYNC && O_SYNC < O__COUNT);
    assert(!strcmp(op->name, "SYNC") && CRS_KIND(op->id) == 0);
    return 0;
}
''')
        unshielded = self.work / 'unshielded/nx/gpu/shader/translator.h'
        unshielded.parent.mkdir(parents=True, exist_ok=True)
        unshielded.write_text(self.original_translator)
        command = ['cc', '-std=gnu11', '-I' + str(self.source / 'src'), '-I' + str(self.work),
                   str(probe), str(self.source / 'src/nx/gpu/shader/decode.c'), '-o', str(self.work / 'sync_probe')]
        before = subprocess.run(command[:1] + ['-I' + str(self.work / 'unshielded')] + command[1:], capture_output=True, text=True)
        self.assertNotEqual(before.returncode, 0)
        self.assertIn('O_SYNC', before.stderr)
        after = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(after.returncode, 0, after.stderr)
        subprocess.run([str(self.work / 'sync_probe')], check=True)

    def test_operand_semantics_before_after_and_source_rollback(self):
        patch = load('zelda_fswz', ROOT / 'tools/patch_scarletnx_zelda_fswz.py')
        baseline = self.compile('baseline')
        output = self.work / 'case.spv'
        for mask in (0x99, 0x66, 0xa5, 0x5a):
            for pair in (0, 1):
                subprocess.run([str(baseline), f'{mask:x}', str(pair), '1', str(output)], check=True)
                expected = maxwell_reference(mask, pair)
                self.assertNotEqual(fragment_red(output), expected)
                # Original substitution ignores a constant lhs, and reverses
                # the sign of the captured SHFL/FSWZADD pattern.
                self.assertEqual(fragment_red(output), [-x for x in expected] if pair else [0.0] * 4)
        self.shader.write_text(patch.transform_shader(self.before))
        self.assertEqual(patch.transform_shader(self.shader.read_text()), self.shader.read_text())
        fixed = self.compile('fixed')
        for mask in (0x99, 0x66, 0xa5, 0x5a):
            for pair in (0, 1):
                with self.subTest(mask=hex(mask), pair=pair):
                    subprocess.run([str(fixed), f'{mask:x}', str(pair), '1', str(output)], check=True)
                    expected = maxwell_reference(mask, pair)
                    for first_lane in (0, 4, 32, 60):
                        self.assertEqual(fragment_red(output, first_lane), expected)
                    validator = os.environ.get('SPIRV_VAL') or shutil.which('spirv-val')
                    if validator:
                        validation = subprocess.run([validator, '--target-env', 'vulkan1.3', str(output)], capture_output=True, text=True)
                        self.assertEqual(validation.returncode, 0, validation.stderr)
            subprocess.run([str(fixed), f'{mask:x}', '0', '0', str(output)], check=True)
        self.assertEqual(patch.transform_shader(self.shader.read_text(), True), self.before)
        self.shader.write_text(self.before)


if __name__ == '__main__':
    unittest.main()
