"""Run the actual pinned jit_init with a stub service to verify cache policy."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('jit_patch', ROOT / 'tools/patch_scarletnx_jit_cache.py')
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


def pinned_source():
    source = Path(os.environ.get('SCARLETNX_SRC', ROOT.parent / 'ScarletNX'))
    if not (source / '.git').exists():
        source = Path.home() / '.cache/lasrecomp-scarletnx-romfs/ScarletNX'
    if not (source / '.git').exists():
        raise unittest.SkipTest('pinned ScarletNX source required')
    return subprocess.check_output(['git', '-C', str(source), 'show',
        '34853eeae5af132e320adbb0193f13344085bf89:' + PATCH.RELATIVE], text=True)


class JitCachePolicy(unittest.TestCase):
    def test_patch_is_reversible_and_refuses_changed_source(self):
        source = pinned_source()
        changed = PATCH.transform(source)
        self.assertEqual(PATCH.transform(changed), changed)
        self.assertEqual(PATCH.transform(changed, True), source)
        self.assertEqual(PATCH.transform(source, True), source)
        with self.assertRaises(ValueError):
            PATCH.transform(source.replace('hints = hints_copy(&hint_count);', 'hints = other();'))

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_actual_jit_init_is_cold_only_for_opted_in_castlevania(self):
        source = PATCH.transform(pinned_source())
        init = 'void jit_init(void)' + source.split('void jit_init(void)', 1)[1].split('\nGuestFn jit_resolve', 1)[0]
        harness = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t u64;
typedef unsigned u32;
typedef struct { u64 base, size, text_off, text_size; } SnxModInfo;
typedef struct { void *image; size_t image_size; u64 base, text_off, text_size; } SnxCodeImage;
typedef struct { unsigned threads; } SnxJitStats;
typedef struct { int alive; } SnxJitService;
typedef struct {
    SnxCodeImage *images; size_t image_count; void *dispatch;
    u64 code_lo, code_hi; const void *aot_addresses, *aot_functions; size_t aot_count;
    int hook_direct_calls, direct_svc; unsigned threads; void (*report)(const void*);
    const char *cache_path;
} SnxJitConfig;
static SnxModInfo mods[1] = {{0, 4, 0, 4}};
static struct { unsigned nmods; SnxModInfo *mods; void *entry_addr, *entry_fn; unsigned nentries; }
    mod = {1, mods, NULL, NULL, 0}, *g_mod = &mod;
static struct { int jit_threads; } g_settings = {4};
static SnxCodeImage *g_jit_images;
static SnxJitService *g_jit, service;
static char g_jit_error[512], g_jit_cache[1400];
static const char *g_cachedir = "/preserved/", *g_exename = "0100BA4026E94000";
static void *g_disp;
static u64 g_code_lo, g_code_hi;
static int cache_enabled, hint_reads, warm_calls, invalidation_hooks, cold_markers;
#define GP(address) ((void*)(uintptr_t)(address))
#define WARN(...) ((void)0)
static void test_log(const char *format, ...) {
    if (strstr(format, "SNX_JIT_COLD_START_V1")) cold_markers++;
}
#define LOG(...) test_log(__VA_ARGS__)
static void jit_log(const void *r) { (void)r; }
static int nvn_trace_active(void) { return 0; }
static SnxJitService *snx_jit_service_new(const SnxJitConfig *c, char *e, size_t n) {
    (void)e; (void)n;
    cache_enabled = c->cache_path != NULL;
    assert(c->threads == 4 && c->images && c->direct_svc == 1);
    if (c->cache_path) {
        char expected[1400];
        snprintf(expected, sizeof expected, "%s%s.jitcache", g_cachedir, g_exename);
        assert(!strcmp(c->cache_path, expected));
    }
    return &service;
}
static u64 *hints_copy(size_t *n) {
    hint_reads++; *n = 2; return calloc(*n, sizeof(u64));
}
static size_t snx_jit_warm(SnxJitService *s, const u64 *h, size_t n) {
    assert(s && h && n == 2); warm_calls++; return n;
}
static void snx_jit_stats(SnxJitService *s, SnxJitStats *stats) {
    assert(s); stats->threads = 4;
}
static void jit_code_invalidate(u64 a, u64 n) { (void)a; (void)n; }
static void mem_set_code_invalidate(void (*f)(u64, u64)) {
    assert(f == jit_code_invalidate); invalidation_hooks++;
}
''' + init + r'''
static void session(int expect_cold) {
    hint_reads = warm_calls = invalidation_hooks = cold_markers = 0;
    jit_init();
    assert(g_jit && invalidation_hooks == 1);
    assert(cache_enabled == !expect_cold && hint_reads == !expect_cold);
    assert(warm_calls == !expect_cold && cold_markers == expect_cold);
    free(g_jit_images); g_jit_images = NULL;
}
int main(void) {
    setenv("SNX_RYUJINX_NATIVE_PROBE", "1", 1);
    for (int i = 0; i < 3; i++) session(1);
    setenv("SNX_RYUJINX_NATIVE_PROBE", "0", 1); session(0);
    unsetenv("SNX_RYUJINX_NATIVE_PROBE"); session(0);
    setenv("SNX_RYUJINX_NATIVE_PROBE", "invalid", 1); session(0);
    setenv("SNX_RYUJINX_NATIVE_PROBE", "1", 1);
    g_exename = "another-game"; session(0);
    puts("JIT_COLD_POLICY_OK: 3 cold sessions, original policy for disabled opt-in and other games");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'policy.c'
            binary = Path(directory) / 'policy'
            file.write_text(harness)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(file), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
