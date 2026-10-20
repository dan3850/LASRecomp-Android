"""Existing private library -> real loader/dispatcher, using synthetic NSOs only."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_mario_full_recompiler import ROOT, make_nso

sys.path.insert(0, str(ROOT / 'tools'))
from mario_boot_profile import START_ABIS, prepare, sdk_startup
from nso import Nso


ADDRESS_COLLISION = '[fixture-address-collision]'


def run_boot_fixture(command, attempts=8):
    """Re-exec only when native process ASLR already occupies guest addresses.

    This happens before any library/guest execution. Never retry dispatch,
    callback, loader, or other mmap errors, and never turn exhaustion into a skip.
    """
    for _ in range(attempts):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode != 3 or ADDRESS_COLLISION not in result.stderr:
            return result
    return result  # Still a failure: the caller must assert actual execution.


class TestFixtureExecution(unittest.TestCase):
    def test_reexecutes_collision_then_requires_a_successful_execution(self):
        collision = subprocess.CompletedProcess(['boot'], 3, '', ADDRESS_COLLISION)
        success = subprocess.CompletedProcess(['boot'], 0, 'guest executed', '')
        with patch('subprocess.run', side_effect=[collision, success]) as run:
            result = run_boot_fixture(['boot'])
        self.assertIs(result, success)
        self.assertEqual(run.call_count, 2)

    def test_does_not_retry_other_mapping_errors(self):
        failure = subprocess.CompletedProcess(['boot'], 3, '', 'mapping: permission denied')
        with patch('subprocess.run', return_value=failure) as run:
            self.assertIs(run_boot_fixture(['boot']), failure)
        self.assertEqual(run.call_count, 1)

    def test_does_not_retry_guest_or_loader_failure(self):
        for code in (2, 5, 7, 8, -6):
            with self.subTest(code=code):
                failure = subprocess.CompletedProcess(['boot'], code, '', 'execution failed')
                with patch('subprocess.run', return_value=failure) as run:
                    self.assertIs(run_boot_fixture(['boot']), failure)
                self.assertEqual(run.call_count, 1)

    def test_collision_exhaustion_remains_a_failure(self):
        failure = subprocess.CompletedProcess(['boot'], 3, '', ADDRESS_COLLISION)
        with patch('subprocess.run', return_value=failure) as run:
            result = run_boot_fixture(['boot'])
        self.assertEqual(result.returncode, 3)
        self.assertEqual(run.call_count, 8)


def make_startup_nso(path, *, sdk, arguments, arrays=False, symbol=None):
    """Synthetic SDK Start calls ready/init, nnMain, then optional fini.

    Each guest constructor/finalizer appends a digit to main's data segment;
    the ordering is checked after actual generated code dispatches callbacks.
    """
    text = bytearray(struct.pack('<I', 0xD503201F) * (0x240 // 4))
    struct.pack_into('<II', text, 0, 0x14000010, 0x1000)

    def address(register, value):
        return [0xD2800000 | (value & 0xFFFF) << 5 | register,
                0xF2A00000 | ((value >> 16) & 0xFFFF) << 5 | register,
                0xF2C00000 | ((value >> 32) & 0xFFFF) << 5 | register]

    def emit(offset, words):
        struct.pack_into('<' + 'I' * len(words), text, offset, *words)

    def marker(offset, digit):
        emit(offset, address(9, 0x7000002000) + [
            0xF940012A,  # ldr x10,[x9]
            0xD280014B,  # mov x11,#10
            0x9B0B7D4A,  # mul x10,x10,x11
            0x9100014A | digit << 10,  # add x10,x10,#digit
            0xF900012A, 0xD65F03C0])

    name = symbol or (START_ABIS[0 if arguments == 5 else 1][0] if sdk else 'nnMain')
    functions = [(name, 0x40), ('ctor_a', 0x100), ('ctor_b', 0x140),
                 ('fini_a', 0x180), ('fini_b', 0x1C0)]
    if sdk:
        words = [0xAA1E03F3, 0xAA0203F4, 0xAA0303F5, 0xAA0403F6,  # save LR,x2,x3,x4
                 0xD63F0280, 0xD63F02A0]  # ready(), init()
        words += address(16, 0x7000000040) + [0xD63F0200]  # real main nnMain
        if arguments == 5:
            words += [0xD63F02C0]  # fini()
        emit(0x40, words + [0xAA1303FE, 0xD65F03C0])
    else:
        marker(0x40, 5)
    for at, digit in zip((0x100, 0x140, 0x180, 0x1C0), (1, 2, 9, 8) if sdk else (3, 4, 7, 6)):
        marker(at, digit)
    ro, data = bytearray(0x600), bytearray(0x100)
    ro[:4] = b'MOD0'
    struct.pack_into('<6i', ro, 4, 0x40, 0x1100, 0x1100, -0x1000, -0x1000, 0)
    dynamic = [(4, 0x1180), (5, 0x1300), (6, 0x1200),
               (25, 0x2008), (27, 16), (26, 0x2018), (28, 16), (7, 0x1400), (8, 96)]
    if not arrays:
        dynamic += [(12, 0x100), (13, 0x180)]
    for i, (tag, value) in enumerate(dynamic + [(0, 0)]):
        struct.pack_into('<QQ', ro, 0x40 + i * 16, tag, value)
    struct.pack_into('<II', ro, 0x180, 1, len(functions) + 1)
    names = bytearray(b'\0')
    for i, (name, offset) in enumerate(functions, 1):
        struct.pack_into('<IBBHQQ', ro, 0x200 + i * 24, len(names), 0x12, 0, 1, offset, 4)
        names += name.encode() + b'\0'
    ro[0x300:0x300 + len(names)] = names
    for i, offset in enumerate((0x100, 0x140, 0x180, 0x1C0)):
        struct.pack_into('<QQq', ro, 0x400 + i * 24, 0x2008 + i * 8, 1027, offset)
    header = bytearray(0x100)
    header[:4] = b'NSO0'
    header[0x40:0x60] = bytes([0x22 if sdk else 0x11]) * 20 + bytes(12)
    cursor = len(header)
    for i, (offset, payload) in enumerate(((0, text), (0x1000, ro), (0x2000, data))):
        struct.pack_into('<III', header, 0x10 + i * 16, cursor, offset, len(payload))
        struct.pack_into('<I', header, 0x60 + i * 4, len(payload))
        cursor += len(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + text + ro + data)


HARNESS = r'''
#include "gamelib.h"
#include "hle.h"
#include "paths.h"
#include "kernel.h"
#include "mario_startup.h"
#include <sys/mman.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
// Host test platform glue only. Loader, dispatcher, profiler and mods below
// are the production runtime sources, not replacements for guest execution.
void plat_commit(uint64_t a,uint64_t n) {(void)a;(void)n;}
void plat_print_backtrace(void) {}
void plat_fatal_notice(void) {}
void plat_crash_handler_install(void) {}
int lasrecomp_external_open(const char *path) {(void)path;return -1;}
int plat_protect(uint64_t a,uint64_t n,int p) {(void)a;(void)n;(void)p;return 0;}
const char *plat_symbol(uint64_t pc,uint64_t *off) {(void)pc;*off=0;return NULL;}
Cpu *kernel_current_cpu(void) {return NULL;}
uint64_t kernel_heap_size(void) {return 0;}
// The resource observer added after this fixture needs a safe reader. These
// tests map exactly the two synthetic module windows and no guest heap.
bool mario_debug_read(uint64_t a,void *out,size_t n) {
    const uint64_t bases[]={MAIN_BASE,SDK_BASE};
    for (int i=0;i<2;i++)
        if (a>=bases[i] && a-bases[i]<0x10000 && n<=0x10000-(a-bases[i])) {
            memcpy(out,(const void *)(uintptr_t)a,n);return true;
        }
    return false;
}
void rt_unwind_point(void) {}
bool rt_resource(const char *a,const char *b,char *c,size_t n) {(void)a;(void)b;(void)c;(void)n;return false;}
// Scheduling glue only: run the actual startup function synchronously so the
// assertions can inspect guest effects. No guest code or callback is replaced.
static KThread main_thread;
static uint64_t initial[5];
KThread *kernel_create_main_thread(uint64_t entry,uint64_t stack,int priority) {
    memset(&main_thread,0,sizeof main_thread);
    main_thread.entry=entry; main_thread.handle=0x123; main_thread.prio=priority;
    main_thread.cpu.sp=(uintptr_t)calloc(1,stack)+stack;
    return &main_thread;
}
void kernel_run_main(KThread *t,uint64_t x0,uint64_t x1,uint64_t x2,uint64_t x3) {
    t->cpu.x[0]=x0;t->cpu.x[1]=x1;t->cpu.x[2]=x2;t->cpu.x[3]=x3;
    memcpy(initial,t->cpu.x,sizeof initial);
    guest_call(&t->cpu,t->entry);
}
static void implemented_service(Cpu *c) {c->x[0]=101;}
// Retain the fixture's sole HLE entry even with a compiler driver that enables
// section GC by default. Production uses whole-archive runtime registration.
__attribute__((used,retain,section(HLE_SECTION)))
static const HleImplEntry test_impl={"test_implemented_service",implemented_service};
static bool reserve_fixture_window(uint64_t base) {
    void *wanted=(void *)(uintptr_t)base;
    // A hint plus an exact-address check never replaces an existing mapping.
    // This single-threaded fixture needs no kernel-specific NOREPLACE flag.
    void *p=mmap(wanted,0x10000,PROT_READ|PROT_WRITE,
                 MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if (p==wanted) return true;
    if (p==MAP_FAILED) {
        int error=errno;
        if (error==EEXIST) fputs("[fixture-address-collision]\n",stderr);
        fprintf(stderr,"fixture guest mapping at %llx failed: %s\n",
                (unsigned long long)base,strerror(error));
    } else {
        munmap(p,0x10000);
        fprintf(stderr,"[fixture-address-collision] fixture guest mapping requested %llx, returned %p\n",
                (unsigned long long)base,p);
    }
    return false;
}
int main(int argc,char **argv) {
    if (argc<3) return 1;
    setenv("LARECOMP_DATA_ROOT",argv[2],1);
    // Match main.c: claim guest addresses before dlopen can allocate there.
    const uint64_t bases[]={MAIN_BASE,SDK_BASE};
    for (int i=0;i<2;i++)
        if (!reserve_fixture_window(bases[i])) return 3;
    char reason[512];
    if (!gamelib_load(argv[1],reason,sizeof reason)) {fprintf(stderr,"%s\n",reason);return 2;}
    loader_load(argv[1]);
    dispatch_init();
    if (argc>3 && !strncmp(argv[3],"startup",7)) {
        if (!strcmp(argv[3],"startup-missing")) g_modules[1].nsyms=1;
        mario_startup(0x100000,44);
        int five=!strncmp(argv[3],"startup5",8);
        int arrays=strstr(argv[3],"-arrays")!=NULL;
        uint64_t sequence=*(uint64_t *)(uintptr_t)(MAIN_BASE+0x2000);
        if (initial[0]!=0x123 || initial[1]!=0 || !initial[2] || !initial[3] ||
            (initial[4]!=0)!=five || main_thread.entry!=SDK_BASE+0x40 || main_thread.prio!=44) return 7;
        uint64_t expected=arrays?(five?123456789:12345):(five?13579:135);
        if (sequence!=expected) {fprintf(stderr,"wrong callback order: %llu expected %llu\n",sequence,expected);return 8;}
        puts("real SDK Start dispatch and module callback order passed");
        return 0;
    }
    if (argc>3 && !strcmp(argv[3],"missing-service")) {
        Cpu c={0}; c.pc=hle_register("Mario::RequiredMissingService",NULL); c.x[30]=MAIN_BASE+0x44;
        rt_dispatch(&c); return 4; // must fail, never synthesize a successful return
    }
    uint64_t memory=0;
    Cpu c={0}; c.x[0]=10; c.x[2]=(uintptr_t)&memory; c.x[5]=SDK_BASE+0x40; c.x[30]=0x1234;
    uint32_t a=0x3fc00000,b=0x40000000;
    memcpy(&c.v[0],&a,4); memcpy(&c.v[1],&b,4);
    c.pc=MAIN_BASE+0x40;
    rt_dispatch(&c);
    uint32_t f; memcpy(&f,&c.v[0],4);
    if (c.x[0]!=29 || c.x[3]!=29 || memory!=29 || c.x[4]!=5 || c.x[30]!=0x1234 || f!=0x40600000) return 5;
    c.pc=hle_register("test_implemented_service",hle_lookup_impl("test_implemented_service"));
    rt_dispatch(&c);
    if (c.x[0]!=101) return 6;
    puts("Mario library loaded; original NSOs matched; real dispatch executed main and sdk");
    return 0;
}
'''


@unittest.skipUnless(shutil.which('clang'), 'Clang required')
class TestMarioBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mario-boot-')
        cls.root = Path(cls.temp.name)
        cls.exefs, cls.out = cls.root / 'exefs', cls.root / 'code'
        make_nso(cls.exefs / 'main')
        make_nso(cls.exefs / 'sdk', sdk=True, entry_name=START_ABIS[1][0])
        built = subprocess.run([sys.executable, str(ROOT / 'tools/mario_full_recompile.py'),
                                str(cls.exefs), '--output', str(cls.out), '--compile',
                                '--simd', 'c', '--host-test'], capture_output=True, text=True)
        if built.returncode:
            raise RuntimeError(built.stdout + built.stderr)
        cls.report = cls.out / 'build-report.json'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.local = tempfile.TemporaryDirectory(prefix='mario-boot-case-')
        self.addCleanup(self.local.cleanup)
        self.folder = Path(self.local.name)
        self.config = self.folder / 'profile'
        self.metadata = prepare(self.report, self.exefs, self.config, host_test=True)

    def test_profile_preserves_library_and_uses_recorded_identity(self):
        library = self.out / 'libmario_test.so'
        stamp = library.stat().st_mtime_ns
        config_stamp = (self.config / 'mario_profile_config.h').stat().st_mtime_ns
        again = prepare(self.report, self.exefs, self.config, host_test=True)
        self.assertEqual(again, self.metadata)
        self.assertEqual(library.stat().st_mtime_ns, stamp)
        self.assertEqual((self.config / 'mario_profile_config.h').stat().st_mtime_ns, config_stamp)
        self.assertEqual(self.metadata['library_id'], json.loads(self.report.read_text())['library_id'])

    def test_android_profile_rejects_host_library(self):
        import platform
        if platform.machine().lower() in ('arm64', 'aarch64'):
            self.skipTest('native fixture already has ARM64 machine type')
        with self.assertRaisesRegex(ValueError, 'ARM64'):
            prepare(self.report, self.exefs, self.config)

    def test_mixed_nso_and_additional_module_are_rejected(self):
        changed = self.folder / 'changed'
        shutil.copytree(self.exefs, changed)
        image = bytearray((changed / 'main').read_bytes())
        image[0x40] ^= 1
        (changed / 'main').write_bytes(image)
        with self.assertRaisesRegex(ValueError, 'differs'):
            prepare(self.report, changed, self.config, host_test=True)
        report = json.loads(self.report.read_text())
        report['additional_nso_modules'] = ['subsdk0']
        altered = self.out / 'extra-module-report.json'
        altered.write_text(json.dumps(report))
        try:
            with self.assertRaisesRegex(ValueError, 'additional modules'):
                prepare(altered, self.exefs, self.config, host_test=True)
        finally:
            altered.unlink()

    def build_harness(self, source_text=HARNESS, linker_flags=()):
        source = self.folder / 'boot.c'
        source.write_text(source_text)
        executable = self.folder / 'boot'
        sources = ['runtime/gamelib.c', 'runtime/loader.c', 'runtime/dispatch.c', 'runtime/mario_startup.c',
                   'runtime/fnprof.c', 'runtime/mods.c']
        command = ['clang', '-std=gnu11', '-O1', '-D_GNU_SOURCE', '-D__ANDROID__',
                   '-DLASRECOMP_MARIO_TEST=1', '-include', str(self.config / 'mario_profile_config.h'),
                   '-I' + str(self.config), '-I' + str(ROOT / 'runtime'), '-Wno-format',
                   '-Wl,--export-dynamic', '-Wl,-rpath,' + str(self.out), str(source),
                   *(str(ROOT / p) for p in sources), *linker_flags,
                   '-ldl', '-lpthread', '-lm', '-o', str(executable)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return executable

    def test_real_android_loader_and_dispatch_execute_existing_library(self):
        executable = self.build_harness()
        result = run_boot_fixture([str(executable), str(self.exefs), str(self.folder)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('real dispatch executed main and sdk', result.stdout)

    def test_guest_windows_are_reserved_before_dynamic_library_allocation(self):
        # Model a native loader allocation that would occupy the guest window
        # if the fixture loaded the library before reserving it. The real
        # dlopen, library identity checks and guest dispatcher still execute.
        source = HARNESS + r'''
#include <dlfcn.h>
void *__real_dlopen(const char *,int);
void *__wrap_dlopen(const char *path,int flags) {
    void *p=mmap((void *)(uintptr_t)MAIN_BASE,0x10000,PROT_READ|PROT_WRITE,
                 MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if (p==MAP_FAILED) abort();
    if (p!=(void *)(uintptr_t)MAIN_BASE) munmap(p,0x10000);
    return __real_dlopen(path,flags);
}
'''
        executable = self.build_harness(source, ('-Wl,--wrap=dlopen',))
        result = run_boot_fixture([str(executable), str(self.exefs), str(self.folder)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('real dispatch executed main and sdk', result.stdout)

    def test_guest_window_collision_is_rejected_without_overwriting_memory(self):
        source = HARNESS[:HARNESS.index('int main(int argc')] + r'''
int main(void) {
    if (!reserve_fixture_window(MAIN_BASE)) return 3;
    unsigned char *p=(void *)(uintptr_t)MAIN_BASE;
    memset(p,0x5a,0x10000);
    if (reserve_fixture_window(MAIN_BASE)) return 11;
    for (int i=0;i<0x10000;i++) if (p[i]!=0x5a) return 12;
    munmap(p,0x10000);
    if (!reserve_fixture_window(MAIN_BASE)) return 13;
    puts("occupied guest window preserved; reservation works after release");
    return 0;
}
'''
        executable = self.build_harness(source)
        result = run_boot_fixture([str(executable)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fixture guest mapping', result.stderr)
        self.assertIn('occupied guest window preserved', result.stdout)

    def test_sdk_start_abis_run_real_guest_callbacks_and_finalizers(self):
        for arguments in (4, 5):
            for arrays in (False, True):
                with self.subTest(arguments=arguments, arrays=arrays):
                    root = self.folder / f'start-{arguments}-{arrays}'
                    self.exefs, self.out, self.config = root / 'exefs', root / 'code', root / 'profile'
                    make_startup_nso(self.exefs / 'main', sdk=False, arguments=arguments, arrays=arrays)
                    make_startup_nso(self.exefs / 'sdk', sdk=True, arguments=arguments, arrays=arrays)
                    built = subprocess.run([sys.executable, str(ROOT / 'tools/mario_full_recompile.py'),
                                            str(self.exefs), '--output', str(self.out), '--compile',
                                            '--simd', 'c', '--host-test'], capture_output=True, text=True)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    metadata = prepare(self.out / 'build-report.json', self.exefs, self.config, host_test=True)
                    self.assertEqual(metadata['startup']['arguments'], arguments)
                    self.assertEqual(metadata['startup']['address'], '0x7004000040')
                    library = self.out / 'libmario_test.so'
                    before = (library.stat().st_mtime_ns, library.read_bytes())
                    executable = self.build_harness()
                    mode = f'startup{arguments}' + ('-arrays' if arrays else '')
                    result = run_boot_fixture([str(executable), str(self.exefs), str(root), mode])
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(f'arguments={arguments}', result.stderr)
                    self.assertIn('real SDK Start dispatch and module callback order passed', result.stdout)
                    self.assertEqual((library.stat().st_mtime_ns, library.read_bytes()), before)
                    missing = run_boot_fixture([str(executable), str(self.exefs), str(root), 'startup-missing'])
                    self.assertNotEqual(missing.returncode, 0)
                    self.assertIn('neither supported nn::init::Start ABI', missing.stderr)

    def test_preflight_rejects_an_unknown_start_signature(self):
        path = self.folder / 'unknown-sdk'
        make_startup_nso(path, sdk=True, arguments=5, symbol='_ZN2nn4init5StartEv')
        with self.assertRaisesRegex(ValueError, 'candidates: _ZN2nn4init5StartEv'):
            sdk_startup(Nso(path), 0x7004000000)

    def test_present_hooks_do_not_read_zelda_memory(self):
        source = self.folder / 'present.c'
        source.write_text(r'''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
bool widescreen_allowed(void);
bool widescreen_frame_boxed(uint64_t frame);
void widescreen_present_crop(uint64_t frame, double shape, float crop[4], double *, double *, double *, double *);
const char *game_level_name(void);
int game_in_play(void);
int main(void) {
    // No guest address space is mapped: an inherited Zelda pointer read faults.
    if (game_in_play() || widescreen_allowed() || widescreen_frame_boxed(1)) return 1;
    if (strcmp(game_level_name(), "Mario")) return 2;
    float crop[4]; double x=0,y=0,w=1920,h=1080;
    widescreen_present_crop(1, 2.0, crop, &x, &y, &w, &h);
    return crop[0]!=0 || crop[1]!=0 || crop[2]!=1 || crop[3]!=1 || x!=0 || y!=0 || w!=1920 || h!=1080;
}
''')
        executable = self.folder / 'present'
        command = ['clang', '-std=gnu11', '-O1', '-ffunction-sections', '-fdata-sections',
                   '-DLASRECOMP_MARIO_TEST=1', '-include', str(self.config / 'mario_profile_config.h'),
                   '-I' + str(self.config), '-I' + str(ROOT / 'runtime'), '-Wno-format',
                   str(source), str(ROOT / 'runtime/hle/widescreen.c'), str(ROOT / 'runtime/hle/warp.c'),
                   '-Wl,--gc-sections', '-lm', '-o', str(executable)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(executable)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_loader_rejects_wrong_nso_and_missing_hle_does_not_return_success(self):
        executable = self.build_harness()
        changed = self.folder / 'changed'
        shutil.copytree(self.exefs, changed)
        image = bytearray((changed / 'main').read_bytes())
        image[0x40] ^= 1
        (changed / 'main').write_bytes(image)
        wrong = run_boot_fixture([str(executable), str(changed), str(self.folder)])
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn('NSO Build ID mismatch', wrong.stderr)
        missing = run_boot_fixture([str(executable), str(self.exefs), str(self.folder), 'missing-service'])
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('[mario-hle] unimplemented Mario::RequiredMissingService', missing.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
