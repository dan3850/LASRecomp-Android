"""Synthetic NSO -> full generator -> shared library -> ARM64 differential test.

All instructions and files here are fixtures, with no proprietary game data.
"""
import ctypes
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import gen
from mario_full_recompile import module_bases
from nso import Nso

try:
    import unicorn as uc
    from unicorn import arm64_const as A
except (ImportError, OSError):
    uc = None

RET, NOP = 0xD65F03C0, 0xD503201F
ENTRY, CALLEE = 0x40, 0x200
MAIN, SDK = 0x7000000000, 0x7004000000


def make_nso(path, *, sdk=False, increment=5, entry_name='start'):
    """Real NSO/MOD0/dynsym layout with a >128-byte caller and two modules."""
    text = bytearray(struct.pack('<I', NOP) * (0x50 // 4 if sdk else 0x210 // 4))
    struct.pack_into('<II', text, 0, 0x14000010, 0x1000)  # entry branch and MOD0 offset
    symbols = [(entry_name, ENTRY)]
    if sdk:
        words = [0x91000084 | (increment << 10), RET]  # add x4,x4,#increment
    else:
        # Preserve guest LR, call another function, call SDK indirectly, loop,
        # write/read memory. NOPs make this a full-size function, not a leaf.
        words = [0xAA1E03F3, 0x94000000 | ((CALLEE - ENTRY - 4) // 4),
                 0xD63F00A0, 0x52800081, 0x91000C00, 0x71000421,
                 0x54FFFFC1, 0xF9000040, 0xF9400043]
        symbols.append(('callee', CALLEE))
        struct.pack_into('<3I', text, CALLEE, 0x91001C00, 0x1E212800, RET)
        struct.pack_into('<2I', text, CALLEE - 8, 0xAA1303FE, RET)  # restore LR
    struct.pack_into('<' + 'I' * len(words), text, ENTRY, *words)
    ro = bytearray(0x400)
    ro[:4] = b'MOD0'
    struct.pack_into('<6i', ro, 4, 0x40, 0x1100, 0x1100, -0x1000, -0x1000, 0)
    for i, (tag, value) in enumerate(((4, 0x1180), (5, 0x1300), (6, 0x1200), (0, 0))):
        struct.pack_into('<QQ', ro, 0x40 + i * 16, tag, value)
    struct.pack_into('<II', ro, 0x180, 1, len(symbols) + 1)
    names = bytearray(b'\0')
    for i, (name, address) in enumerate(symbols, 1):
        struct.pack_into('<IBBHQQ', ro, 0x200 + i * 24, len(names), 0x12, 0, 1, address, 4)
        names += name.encode() + b'\0'
    ro[0x300:0x300 + len(names)] = names
    data = bytes(0x100)
    header = bytearray(0x100)
    header[:4] = b'NSO0'
    header[0x40:0x60] = bytes([0x22 if sdk else 0x11]) * 20 + bytes(12)
    cursor = len(header)
    for i, (memory, payload) in enumerate(((0, text), (0x1000, ro), (0x2000, data))):
        struct.pack_into('<III', header, 0x10 + i * 16, cursor, memory, len(payload))
        struct.pack_into('<I', header, 0x60 + i * 4, len(payload))
        cursor += len(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + text + ro + data)


class Cpu(ctypes.Structure):
    _fields_ = [('x', ctypes.c_uint64 * 32), ('sp', ctypes.c_uint64),
                ('pc', ctypes.c_uint64), ('nzcv', ctypes.c_uint64),
                ('rest', ctypes.c_uint8 * (512 - 280)),
                ('v', (ctypes.c_uint64 * 2) * 32)]


class Tables(ctypes.Structure):
    _fields_ = [('abi', ctypes.c_uint32), ('id', ctypes.c_char_p),
                ('main_addrs', ctypes.POINTER(ctypes.c_uint64)),
                ('sdk_addrs', ctypes.POINTER(ctypes.c_uint64)),
                ('main_fns', ctypes.POINTER(ctypes.c_void_p)),
                ('sdk_fns', ctypes.POINTER(ctypes.c_void_p)),
                ('main_count', ctypes.POINTER(ctypes.c_uint64)),
                ('sdk_count', ctypes.POINTER(ctypes.c_uint64))]


SUPPORT = r'''
#include "gamelib.h"
#include <stdlib.h>
volatile int g_fnprof;
static const GameLibTables *tables;
void test_set_tables(const GameLibTables *t) { tables=t; }
void fnprof_hit(uint64_t a, uint64_t b, uint64_t d) { (void)a; (void)b; (void)d; }
void rt_dispatch(Cpu *c) {
    for (uint64_t i=0; i<*tables->main_count; ++i)
        if (tables->main_addrs[i]==c->pc) { tables->main_fns[i](c); return; }
    for (uint64_t i=0; i<*tables->sdk_count; ++i)
        if (tables->sdk_addrs[i]==c->pc) { tables->sdk_fns[i](c); return; }
    abort();
}
void rt_udf(Cpu *c,uint64_t pc) { (void)c; (void)pc; abort(); }
void rt_brk(Cpu *c,uint32_t v,uint64_t pc) { (void)c; (void)v; (void)pc; abort(); }
void rt_svc(Cpu *c,uint32_t v,uint64_t pc) { (void)c; (void)v; (void)pc; abort(); }
uint64_t rt_ticks(void) { return 0; }
'''


class TestProfiles(unittest.TestCase):
    def test_mario_keeps_original_code_at_zelda_patch_collisions(self):
        code = struct.pack('<2I', 0xD2800020, RET)  # mov x0,#1
        nso = SimpleNamespace(image=code, text=(0, len(code)), build_id='1234')
        address = MAIN
        with patch.dict(gen.PATCHES, {address: lambda *_: 'c->x[0]=999;'}, clear=True), \
             patch.dict(gen.RANDO_CODE, {0: [0xD2800040]}, clear=True):
            mario = gen.Module('main', None, address, 'c', nso=nso, profile='mario', expected_build_id='1234')
            body = '\n'.join(mario.emit_function(address, address + len(code), {address}, {}, {}))
            self.assertNotIn('999', body)
            self.assertNotIn('rando_word', body)
            self.assertIn('0x1ull', body)
            zelda = gen.Module('main', None, address, 'c', nso=nso)
            zelda_body = '\n'.join(zelda.emit_function(address, address + len(code), {address}, {}, {}))
            self.assertIn('rando_word', zelda_body)
            with self.assertRaisesRegex(ValueError, 'Zelda-only'):
                gen.enable_stable60_menu(mario, True, explicit=True)
            self.assertFalse(gen.enable_stable60_menu(mario, True))

    def test_build_id_checked_before_output_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_nso(root / 'main')
            out = root / 'generated'
            result = subprocess.run([sys.executable, str(ROOT / 'tools/gen.py'), 'main',
                                     str(root / 'main'), hex(MAIN), str(out), '--profile', 'mario',
                                     '--expect-build-id', 'bad', '--simd', 'c'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Build ID mismatch', result.stderr)
            self.assertFalse(out.exists())

    def test_large_main_moves_sdk_without_overlapping_hle(self):
        bases = module_bases(0x5001000, 0x100000)
        self.assertEqual(bases['main'], MAIN)
        self.assertGreaterEqual(bases['sdk'], MAIN + 0x5001000)
        self.assertEqual(bases['sdk'] & 0xFFFF, 0)
        with self.assertRaisesRegex(ValueError, 'HLE'):
            module_bases(0x80000000, 0x100000)


@unittest.skipUnless(shutil.which('clang'), 'Clang required for native compilation')
class TestFullPipeline(unittest.TestCase):
    def run_builder(self, exefs, out, simd='c'):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/mario_full_recompile.py'),
                                 str(exefs), '--output', str(out), '--simd', simd, '--compile',
                                 '--host-test', '--jobs', '2'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((out / 'build-report.json').read_text())

    def test_arm64_inline_simd_sources_compile_for_android(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exefs, out = root / 'exefs', root / 'out'
            make_nso(exefs / 'main')
            make_nso(exefs / 'sdk', sdk=True)
            generated = subprocess.run([sys.executable, str(ROOT / 'tools/mario_full_recompile.py'),
                                        str(exefs), '--output', str(out), '--simd', 'asm'],
                                       capture_output=True, text=True)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            # Compile real ARM64 inline assembly without needing a full Android
            # NDK on the development host. Only the C declaration is supplied;
            # no runtime or game functions are replaced in generated code.
            include = root / 'include'
            include.mkdir()
            (include / 'string.h').write_text('#include <stddef.h>\n'
                'void *memcpy(void *, const void *, size_t);\n'
                'void *memset(void *, int, size_t);\n')
            resource = subprocess.check_output(['clang', '-print-resource-dir'], text=True).strip()
            for source in (out / 'generated').glob('*/*.c'):
                obj = root / (source.stem + '.o')
                result = subprocess.run(['clang', '--target=aarch64-linux-android24', '-ffreestanding',
                                         '-nostdinc', '-isystem', str(Path(resource) / 'include'),
                                         '-I' + str(include), '-I' + str(ROOT / 'runtime'),
                                         '-O1', '-c', str(source), '-o', str(obj)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(struct.unpack_from('<H', obj.read_bytes(), 18)[0], 183)

    def test_missing_unicorn_links_and_executes_memory_loaded_branch_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exefs, out = root / 'exefs', root / 'out'
            make_nso(exefs / 'main')
            make_nso(exefs / 'sdk', sdk=True)
            # A branch target read from memory is not recognized by the old
            # address-arithmetic heuristic. Both interior targets and a tail
            # jump to another module must still execute without Unicorn.
            image = bytearray((exefs / 'main').read_bytes())
            start = 0x100 + ENTRY
            image[start:0x100 + CALLEE] = struct.pack('<I', NOP) * ((CALLEE - ENTRY) // 4)
            struct.pack_into('<3I', image, start, 0xAA1E03F3, 0xF9400046, 0xD61F00C0)
            struct.pack_into('<3I', image, start + 16, 0x91000C00, 0xAA1303FE, RET)
            struct.pack_into('<3I', image, start + 32, 0x91001C00, 0xAA1303FE, RET)
            (exefs / 'main').write_bytes(image)
            blocked = root / 'without-unicorn'
            blocked.mkdir()
            (blocked / 'unicorn.py').write_text('raise ImportError("Unicorn intentionally unavailable")\n')
            environment = dict(os.environ)
            environment['PYTHONPATH'] = str(blocked) + os.pathsep + environment.get('PYTHONPATH', '')
            built = subprocess.run([sys.executable, str(ROOT / 'tools/mario_full_recompile.py'),
                                    str(exefs), '--output', str(out), '--simd', 'c', '--compile',
                                    '--host-test'], env=environment, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            report = json.loads((out / 'build-report.json').read_text())
            self.assertEqual(report['status'], 'linked_requires_runtime')
            self.assertEqual(report['jump_table_analysis'], 'local-dispatch')
            self.assertGreater(report['modules']['main']['stats']['br_without_unicorn'], 0)
            self.assertEqual(report['modules']['main']['jump_table_analysis'], 'local-dispatch')
            harness = root / 'branch-test.c'
            harness.write_text(SUPPORT + r'''
extern const GameLibTables *mario_test_tables(void);
int main(void) {
    const GameLibTables *t=mario_test_tables();
    test_set_tables(t);
    GuestFn entry=0;
    for (uint64_t i=0; i<*t->main_count; ++i)
        if (t->main_addrs[i]==0x7000000040ull) entry=t->main_fns[i];
    if (!entry) return 1;
    const uint64_t targets[]={0x7000000050ull,0x7000000060ull,0x7004000040ull};
    const uint64_t expected[]={13,17,10};
    for (int i=0; i<3; ++i) {
        Cpu c={0};
        c.x[0]=10; c.x[2]=(uintptr_t)&targets[i]; c.x[30]=0x1234;
        entry(&c);
        if (c.x[0]!=expected[i] || c.x[30]!=0x1234 || c.x[4]!=(i==2 ? 5u : 0u)) return 2+i;
    }
    return 0;
}
''')
            executable = root / 'branch-test'
            linked = subprocess.run(['clang', '-O1', '-Wl,--export-dynamic',
                                     '-I' + str(ROOT / 'runtime'), str(harness),
                                     str(out / 'libmario_test.so'), '-Wl,-rpath,' + str(out),
                                     '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(linked.returncode, 0, linked.stderr)
            ran = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_whole_modules_link_and_reuse_only_unchanged_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exefs, out = root / 'exefs', root / 'out'
            make_nso(exefs / 'main')
            make_nso(exefs / 'sdk', sdk=True)
            report = self.run_builder(exefs, out)
            self.assertEqual(report['status'], 'linked_requires_runtime')
            self.assertFalse(report['runtime_ready'])
            self.assertFalse(report['boot_tested'])
            self.assertGreater(report['modules']['main']['functions'], 1)
            self.assertTrue(report['modules']['main']['complete'])
            self.assertFalse(report['modules']['main']['stable60_menu'])
            self.assertEqual(report['link']['elf_machine'], 183 if platform_arm() else 62)
            self.assertFalse(any(s.startswith('f_') for s in report['link']['undefined_symbols']))
            library = out / 'libmario_test.so'
            mtime = library.stat().st_mtime_ns
            again = self.run_builder(exefs, out)
            self.assertEqual(again['compiled_objects'], 0)
            self.assertEqual(library.stat().st_mtime_ns, mtime)
            chunk = out / 'generated/main/main_000.c'
            original = chunk.read_bytes()
            chunk.write_text('#error corrupt generated cache\n')
            repaired = self.run_builder(exefs, out)
            self.assertEqual(chunk.read_bytes(), original)
            self.assertEqual(repaired['compiled_objects'], 0)
            # Alter just the SDK behavior: main objects stay reusable; entry id
            # and SDK code change. No stale .so or Zelda object is linked.
            make_nso(exefs / 'sdk', sdk=True, increment=6)
            changed = self.run_builder(exefs, out)
            self.assertEqual(changed['compiled_objects'], 2)
            self.assertGreater(changed['reused_objects'], 0)
            self.assertNotEqual(changed['library_id'], report['library_id'])

    @unittest.skipUnless(uc, 'Unicorn required for full ARM64 differential execution')
    def test_calls_backward_loop_memory_and_simd_match_original_arm64(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exefs, out = root / 'exefs', root / 'out'
            make_nso(exefs / 'main')
            make_nso(exefs / 'sdk', sdk=True)
            report = self.run_builder(exefs, out, 'asm' if platform_arm() else 'c')
            support = root / 'support.c'
            support.write_text(SUPPORT)
            subprocess.run(['clang', '-std=gnu11', '-O1', '-shared', '-fPIC',
                            '-I' + str(ROOT / 'runtime'), str(support), '-o', str(root / 'support.so')],
                           check=True, capture_output=True)
            runtime = ctypes.CDLL(str(root / 'support.so'), mode=ctypes.RTLD_GLOBAL)
            library = ctypes.CDLL(str(out / 'libmario_test.so'))
            library.mario_test_tables.restype = ctypes.POINTER(Tables)
            tables = library.mario_test_tables()
            self.assertEqual(tables.contents.id.decode(), report['library_id'])
            runtime.test_set_tables.argtypes = [ctypes.POINTER(Tables)]
            runtime.test_set_tables(tables)
            count = tables.contents.main_count[0]
            entry = next(tables.contents.main_fns[i] for i in range(count)
                         if tables.contents.main_addrs[i] == MAIN + ENTRY)
            native = ctypes.CFUNCTYPE(None, ctypes.POINTER(Cpu))(entry)
            original = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
            for name, base in (('main', MAIN), ('sdk', SDK)):
                nso = Nso(exefs / name)
                original.mem_map(base, len(nso.image))
                original.mem_write(base, bytes(nso.image))
            original.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
            ram = ctypes.create_string_buffer(0x3000)
            pointer = (ctypes.addressof(ram) + 0xFFF) & ~0xFFF
            original.mem_map(pointer, 0x1000)
            sentinel = MAIN + 0x8000
            rng = random.Random(20261019)
            for serial in range(24):
                state = Cpu()
                for i in range(31):
                    state.x[i] = rng.getrandbits(64)
                state.x[2], state.x[5], state.x[30] = pointer, SDK + ENTRY, sentinel
                state.sp, state.nzcv = pointer + 0x800, rng.randrange(16) << 28
                state.v[0][0] = struct.unpack('<I', struct.pack('<f', float(serial)))[0]
                state.v[1][0] = struct.unpack('<I', struct.pack('<f', 1.5))[0]
                ctypes.memset(pointer, 0xA5, 0x1000)
                original.mem_write(pointer, b'\xA5' * 0x1000)
                for i in range(29):
                    original.reg_write(A.UC_ARM64_REG_X0 + i, state.x[i])
                original.reg_write(A.UC_ARM64_REG_X29, state.x[29])
                original.reg_write(A.UC_ARM64_REG_X30, state.x[30])
                original.reg_write(A.UC_ARM64_REG_SP, state.sp)
                original.reg_write(A.UC_ARM64_REG_NZCV, state.nzcv)
                for i in range(32):
                    original.reg_write(A.UC_ARM64_REG_Q0 + i, state.v[i][0] | state.v[i][1] << 64)
                original.emu_start(MAIN + ENTRY, sentinel, count=4096)
                self.assertEqual(original.reg_read(A.UC_ARM64_REG_PC), sentinel)
                native(ctypes.byref(state))
                expected = [original.reg_read(A.UC_ARM64_REG_X0 + i) for i in range(29)]
                expected += [original.reg_read(A.UC_ARM64_REG_X29), original.reg_read(A.UC_ARM64_REG_X30)]
                self.assertEqual(list(state.x)[:31], expected, serial)
                self.assertEqual(state.sp, original.reg_read(A.UC_ARM64_REG_SP))
                self.assertEqual(state.nzcv & 0xF0000000, original.reg_read(A.UC_ARM64_REG_NZCV))
                self.assertEqual(ctypes.string_at(pointer, 0x1000), bytes(original.mem_read(pointer, 0x1000)))
                for i in range(32):
                    self.assertEqual(state.v[i][0] | state.v[i][1] << 64,
                                     original.reg_read(A.UC_ARM64_REG_Q0 + i), (serial, i))


def platform_arm():
    import platform
    return platform.machine().lower() in ('arm64', 'aarch64')


if __name__ == '__main__':
    unittest.main(verbosity=2)
