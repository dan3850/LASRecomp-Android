"""Existing private library -> real loader/dispatcher, using synthetic NSOs only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_mario_full_recompiler import ROOT, make_nso

sys.path.insert(0, str(ROOT / 'tools'))
from mario_boot_profile import prepare


HARNESS = r'''
#include "gamelib.h"
#include "hle.h"
#include "paths.h"
#include <sys/mman.h>
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
void rt_unwind_point(void) {}
bool rt_resource(const char *a,const char *b,char *c,size_t n) {(void)a;(void)b;(void)c;(void)n;return false;}
HLE_FUNC("test_implemented_service", implemented_service) {c->x[0]=101;}
int main(int argc,char **argv) {
    if (argc<3) return 1;
    setenv("LARECOMP_DATA_ROOT",argv[2],1);
    char reason[512];
    if (!gamelib_load(argv[1],reason,sizeof reason)) {fprintf(stderr,"%s\n",reason);return 2;}
    const uint64_t bases[]={MAIN_BASE,SDK_BASE};
    for (int i=0;i<2;i++) {
        void *p=mmap((void *)(uintptr_t)bases[i],0x10000,PROT_READ|PROT_WRITE,
                    MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
        if (p!=(void *)(uintptr_t)bases[i]) return 3;
    }
    loader_load(argv[1]);
    dispatch_init();
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
        make_nso(cls.exefs / 'sdk', sdk=True)
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

    def build_harness(self):
        source = self.folder / 'boot.c'
        source.write_text(HARNESS)
        executable = self.folder / 'boot'
        sources = ['runtime/gamelib.c', 'runtime/loader.c', 'runtime/dispatch.c',
                   'runtime/fnprof.c', 'runtime/mods.c']
        command = ['clang', '-std=gnu11', '-O1', '-D_GNU_SOURCE', '-D__ANDROID__',
                   '-DLASRECOMP_MARIO_TEST=1', '-include', str(self.config / 'mario_profile_config.h'),
                   '-I' + str(self.config), '-I' + str(ROOT / 'runtime'), '-Wno-format',
                   '-Wl,--export-dynamic', '-Wl,-rpath,' + str(self.out), str(source),
                   *(str(ROOT / p) for p in sources), '-ldl', '-lpthread', '-lm', '-o', str(executable)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return executable

    def test_real_android_loader_and_dispatch_execute_existing_library(self):
        executable = self.build_harness()
        result = subprocess.run([str(executable), str(self.exefs), str(self.folder)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('real dispatch executed main and sdk', result.stdout)

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
        wrong = subprocess.run([str(executable), str(changed), str(self.folder)],
                               capture_output=True, text=True)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn('NSO Build ID mismatch', wrong.stderr)
        missing = subprocess.run([str(executable), str(self.exefs), str(self.folder), 'missing-service'],
                                 capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('[mario-hle] unimplemented Mario::RequiredMissingService', missing.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
