"""Execute production experiment helpers and their actual injected wait/cache guards."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


OPT = module('perf_opt', ROOT / 'tools/patch_scarletnx_zelda_perf_opt.py')
PERF = module('perf_base', ROOT / 'tools/patch_scarletnx_zelda_perf.py')
LIVE = module('live_v1', ROOT / 'tools/ryujinx-nativeaot/patch_scarletnx_live_probe.py')
FSWZ = module('zelda_fswz_stack', ROOT / 'tools/patch_scarletnx_zelda_fswz.py')
D7 = module('d7_fswz_stack', ROOT / 'tools/patch_scarletnx_fswzadd.py')
BINDLESS = module('bindless_fswz_stack', ROOT / 'tools/patch_scarletnx_bindless_diag.py')
HASH_SPAN = module('hash_span_stack', ROOT / 'tools/patch_scarletnx_zelda_hash_span.py')
TRANSFER = module('transfer_stack', ROOT / 'tools/patch_scarletnx_zelda_transfer.py')
UNIFORM = module('uniform_stack', ROOT / 'tools/patch_scarletnx_zelda_uniform.py')
CLEAR_LOAD = module('clear_load_stack', ROOT / 'tools/patch_scarletnx_zelda_clear_load.py')
UB_EXTENT = module('ub_extent_stack', ROOT / 'tools/patch_scarletnx_zelda_ub_extent.py')
BIND_REUSE = module('bind_reuse_stack', ROOT / 'tools/patch_scarletnx_zelda_bind_reuse.py')
SHADOW_CAPTURE = module('shadow_capture_stack', ROOT / 'tools/patch_scarletnx_zelda_shadow_capture.py')
WW_DIAG = module('ww_diag_stack', ROOT / 'tools/patch_scarletnx_zelda_ww_diag.py')
VB_POOL = module('vb_pool_stack', ROOT / 'tools/patch_scarletnx_zelda_vb_pool.py')
SRC = Path(os.environ.get('SCARLETNX_TEST_SRC', ROOT.parent / 'ScarletNX-audit'))
PIN = '34853eeae5af132e320adbb0193f13344085bf89'


def compile_run(source, root, *args):
    path = root / 'test.c'
    path.write_text(source)
    binary = root / 'test'
    build = subprocess.run(['cc', '-std=gnu11', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-I' + str(ROOT / 'tools/zelda-perf'), str(path), '-ldl', '-o', str(binary)],
                           capture_output=True, text=True)
    if build.returncode:
        raise AssertionError(build.stderr)
    run = subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stderr)
    return run.stdout


class ExperimentTests(unittest.TestCase):
    def test_atomic_patch_rollback_and_abi2_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            before = {}
            for name, pairs in OPT.replacements().items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                before[name] = '\n/* anchor */\n'.join(old for old, new in pairs)
                path.write_text(before[name])
            OPT.apply(root)
            once = {name: (root / name).read_text() for name in before}
            OPT.apply(root)
            self.assertEqual(once, {name: (root / name).read_text() for name in before})
            OPT.apply(root, True)
            self.assertEqual(before, {name: (root / name).read_text() for name in before})
            OPT.apply(root, True)
            pipeline = root / 'src/nx/gpu/vk/pipeline.c'
            pipeline.write_text(pipeline.read_text() + '\n snx_rn_try_v2')
            with self.assertRaisesRegex(ValueError, 'ABI 2'):
                OPT.apply(root)
            self.assertEqual((root / 'src/nx/gpu/vk/cmd.c').read_text(), before['src/nx/gpu/vk/cmd.c'])

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_only_successful_waits_publish_completion_no_prediction_on_error(self):
        # The original pinned function, then the SAME replacements used in cmd.c.
        wait = '''static void timeline_wait(u64 value) {
    VkSemaphoreWaitInfo wi = {
        .sType = VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO, .semaphoreCount = 1, .pSemaphores = &g_gsem, .pValues = &value};
    gpu_wait_note("a graphics submission", value);
    VK_OK(vkWaitSemaphores(g_vk.dev, &wi, UINT64_MAX));
    gpu_wait_note(NULL, 0);
}
'''
        for old, new in PERF.replacements()['src/nx/gpu/vk/cmd.c'] + OPT.replacements()['src/nx/gpu/vk/cmd.c']:
            if old in wait:
                wait = wait.replace(old, new)
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
typedef uint64_t u64;
typedef int VkResult;
typedef struct { int sType, semaphoreCount; int* pSemaphores; u64* pValues; } VkSemaphoreWaitInfo;
#define VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO 0
#define VK_OK(x) ((x) == 0)
#define LOG(...) ((void)0)
static struct { int dev; } g_vk;
static int g_gsem, snx_perf_on = 1, calls, wait_status, elided;
enum { SNX_PM_WAIT_ELIDED, SNX_PM_TIMELINE };
static u64 plat_ns(void) { static u64 n; return ++n; }
static void gpu_wait_note(const char* note, u64 v) { (void)note; (void)v; }
static void snx_perf_add(int kind, u64 ns, u64 n) { (void)ns; if (kind == SNX_PM_WAIT_ELIDED) elided += (int)n; }
static int vkWaitSemaphores(int dev, const VkSemaphoreWaitInfo* wi, u64 timeout) {
    (void)dev; assert(wi->semaphoreCount == 1 && wi->pSemaphores == &g_gsem && timeout == UINT64_MAX);
    calls++; return wait_status;
}
#include "known_complete.h"
''' + wait + r'''
static void* mark(void* arg) { snx_known_note((u64)(uintptr_t)arg); return NULL; }
int main(void) {
    snx_known_init(); timeline_wait(7); timeline_wait(7); assert(calls == 2);
    setenv("SNX_VK_KNOWN_COMPLETE", "1", 1); snx_known_init(); calls = 0;
    timeline_wait(0); assert(!calls && elided == 1);
    wait_status = -4; timeline_wait(7); assert(calls == 1 && !snx_known_ready(7));
    wait_status = 0; timeline_wait(7); assert(calls == 2 && snx_known_ready(7));
    timeline_wait(3); timeline_wait(7); assert(calls == 2 && elided == 3);
    timeline_wait(8); assert(calls == 3 && snx_known_ready(8) && !snx_known_ready(9));
    pthread_t t[16];
    for (uintptr_t i = 0; i < 16; i++) assert(!pthread_create(&t[i], NULL, mark, (void*)(100 + i)));
    for (int i = 0; i < 16; i++) assert(!pthread_join(t[i], NULL));
    assert(snx_known_ready(115) && !snx_known_ready(116));
    snx_known_note(2); assert(snx_known_ready(115));
    setenv("SNX_VK_KNOWN_COMPLETE", "0", 1); snx_known_init();
    timeline_wait(1); timeline_wait(1); assert(calls == 5 && !snx_known_ready(1));
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            compile_run(program, Path(d))

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_cache_namespaces_binary_driver_changes_and_preserves_legacy_files(self):
        pairs = OPT.replacements()['src/nx/gpu/vk/pipeline.c']
        load = next(new for old, new in pairs if old.startswith('    PFileMap data;'))
        path_code = next(new for old, new in pairs if 'snprintf(g_pcache_path' in old)
        save = next(new for old, new in pairs if old.startswith('void vk_pipeline_save'))
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
typedef uint64_t u64;
typedef uint32_t u32;
typedef struct { void* data; size_t size; } PFileMap;
#define LOG(...) ((void)0)
#define WARN(...) ((void)0)
static struct { int shader_captures; } g_settings;
static struct { struct { u32 vendorID, deviceID, driverVersion; unsigned char pipelineCacheUUID[16]; } props; } g_vk;
static char translator_path[1024], runtime_path[1024];
static int unavailable, maps, unmaps, saves, locks, g_psave;
static char g_cache_dir[1100], g_pcache_path[1200];
static const char* g_exename = "01006BB00C6F0000";
static void vk_pipeline_init(void) {}
static void adapt(void) {}
static void (*snx_rn_adapt)(void) = adapt;
static int snx_rn_init(void) { return !unavailable; }
static u64 vk_hash(const void* p, u64 n) {
    const unsigned char* b = p; u64 h = 1469598103934665603ull;
    while (n--) h = (h ^ *b++) * 1099511628211ull;
    return h;
}
static int plat_file_map(PFileMap* m, const char* p) {
    maps++; FILE* f = fopen(p, "rb"); if (!f) return -1;
    fseek(f, 0, SEEK_END); m->size = (size_t)ftell(f); rewind(f);
    m->data = malloc(m->size); assert(m->data);
    assert(fread(m->data, 1, m->size, f) == m->size); fclose(f); return 0;
}
static void plat_file_unmap(PFileMap* m) { if (m->data) { unmaps++; free(m->data); m->data = NULL; } }
static int fake_dladdr(const void* fn, Dl_info* info) {
    info->dli_fname = fn == (const void*)snx_rn_adapt ? translator_path : runtime_path; return 1;
}
#define dladdr fake_dladdr
#include "ryu_cache.h"
static void pm_lock(int* p) { (void)p; locks++; }
static size_t initial_size;
static void configure(void) {
''' + path_code + r'''
}
static void load_cache(void) {
''' + load + r'''
        initial_size = data.size;
    }
    plat_file_unmap(&data);
}
''' + save + r'''
    saves++;
}
static void put(const char* path, const char* text) {
    FILE* f = fopen(path, "wb"); assert(f); fputs(text, f); assert(!fclose(f));
}
int main(int argc, char** argv) {
    assert(argc == 2);
    snprintf(g_cache_dir, sizeof g_cache_dir, "%s", argv[1]);
    snprintf(runtime_path, sizeof runtime_path, "%s/runtime.bin", argv[1]);
    snprintf(translator_path, sizeof translator_path, "%s/translator.bin", argv[1]);
    put(runtime_path, "runtime-A"); put(translator_path, "translator-A");
    configure(); assert(!snx_ryu_persistent && strstr(g_pcache_path, "vk_pipelines.bin"));
    /* Native backend still uses the original policy. */
    load_cache(); vk_pipeline_save(); assert(saves == 1 && locks == 1 && initial_size);
    int old_maps = maps; initial_size = 0;
    setenv("SNX_RYUJINX_NATIVE_PROBE", "1", 1);
    configure(); load_cache(); vk_pipeline_save();
    assert(!snx_ryu_persistent && maps == old_maps && saves == 1 && !initial_size);
    setenv("SNX_RYU_PERSIST", "1", 1); configure();
    assert(snx_ryu_persistent && !strstr(g_pcache_path, "vk_pipelines.bin"));
    char first[1200]; strcpy(first, g_pcache_path);
    put(first, "new isolated driver cache"); load_cache(); vk_pipeline_save();
    assert(initial_size && saves == 2);
    configure(); assert(!strcmp(first, g_pcache_path)); /* same binary, new startup */
    put(translator_path, "translator-B"); configure(); assert(strcmp(first, g_pcache_path));
    put(translator_path, "translator-A"); configure(); assert(!strcmp(first, g_pcache_path));
    put(runtime_path, "runtime-B"); configure(); assert(strcmp(first, g_pcache_path));
    put(runtime_path, "runtime-A"); g_vk.props.driverVersion++; configure(); assert(strcmp(first, g_pcache_path));
    g_vk.props.driverVersion--; g_vk.props.pipelineCacheUUID[0]++; configure(); assert(strcmp(first, g_pcache_path));
    g_settings.shader_captures = 1; configure(); assert(!snx_ryu_persistent);
    g_settings.shader_captures = 0; setenv("SNX_SHADER_CORPUS", "capture", 1);
    configure(); assert(!snx_ryu_persistent); unsetenv("SNX_SHADER_CORPUS");
    unavailable = 1; configure(); assert(!snx_ryu_persistent); unavailable = 0;
    snx_ryu_cache_setup(1000, 256, 1200); assert(!snx_ryu_persistent); /* never truncate namespace */
    assert(maps == unmaps);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            native = root / 'vk_pipelines.bin'
            shader = root / '01006BB00C6F0000.vkshaders'
            native.write_bytes(b'legacy driver cache preserved')
            shader.write_bytes(b'legacy shader cache preserved')
            compile_run(program, root, root)
            self.assertEqual(native.read_bytes(), b'legacy driver cache preserved')
            self.assertEqual(shader.read_bytes(), b'legacy shader cache preserved')

    @unittest.skipUnless((SRC / '.git').exists(), 'optional pinned ScarletNX checkout unavailable')
    def test_entire_patch_stack_on_real_pinned_source_restores_every_byte(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            names = (set(PERF.replacements()) | set(OPT.replacements()) | set(TRANSFER.replacements()) |
                     set(UNIFORM.replacements()) | set(CLEAR_LOAD.replacements()) | set(UB_EXTENT.replacements()) |
                     set(BIND_REUSE.replacements()) | set(SHADOW_CAPTURE.replacements()) |
                     set(WW_DIAG.replacements()) | set(VB_POOL.replacements()))
            names.add('src/nx/gpu/shader/spirv_translate.c')
            before = {}
            for name in names:
                before[name] = subprocess.check_output(['git', '-C', str(SRC), 'show', PIN + ':' + name])
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before[name])
            LIVE.apply(root)
            PERF.apply(root, 'integration-test')
            OPT.apply(root)
            OPT.apply(root)
            HASH_SPAN.apply(root)
            HASH_SPAN.apply(root)
            TRANSFER.apply(root)
            TRANSFER.apply(root)
            UNIFORM.apply(root)
            UNIFORM.apply(root)
            CLEAR_LOAD.apply(root)
            CLEAR_LOAD.apply(root)
            UB_EXTENT.apply(root)
            UB_EXTENT.apply(root)
            BIND_REUSE.apply(root)
            BIND_REUSE.apply(root)
            SHADOW_CAPTURE.apply(root)
            SHADOW_CAPTURE.apply(root)
            WW_DIAG.apply(root)
            WW_DIAG.apply(root)
            VB_POOL.apply(root)
            VB_POOL.apply(root)
            shader = root / 'src/nx/gpu/shader/spirv_translate.c'
            shader.write_text(D7.apply(BINDLESS.transform(shader.read_text())))
            FSWZ.apply(root)
            once = {name: (root / name).read_bytes() for name in names}
            FSWZ.apply(root)
            self.assertEqual(once, {name: (root / name).read_bytes() for name in names})
            FSWZ.apply(root, True)
            VB_POOL.apply(root, True)
            WW_DIAG.apply(root, True)
            SHADOW_CAPTURE.apply(root, True)
            BIND_REUSE.apply(root, True)
            UB_EXTENT.apply(root, True)
            CLEAR_LOAD.apply(root, True)
            UNIFORM.apply(root, True)
            TRANSFER.apply(root, True)
            HASH_SPAN.apply(root, True)
            shader.write_text(BINDLESS.transform(D7.apply(shader.read_text(), True), True))
            OPT.apply(root, True)
            PERF.apply(root, revert=True)
            LIVE.apply(root, revert=True)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in names})
            self.assertFalse((root / 'src/nx/gpu/vk/snx_hash_span.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_transfer.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_uniform.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_clear_load.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_ub_extent.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_bind_reuse.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_shadow_capture.h').exists())
            self.assertFalse((root / 'src/nx/runtime/platform/snx_ww_diag.h').exists())
            self.assertFalse((root / 'src/nx/gpu/vk/snx_vb_pool.h').exists())

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_native_capture_bypasses_real_prewarm_and_normal_policy_resumes(self):
        # Capture must exercise vk_shader_get, not silently reuse old SPIR-V
        # modules and export only the few newly encountered shaders.
        source = subprocess.check_output(['git', '-C', str(SRC), 'show',
                                          PIN + ':src/nx/gpu/vk/pipeline.c'], text=True)
        source = LIVE.transform(source)
        for old, new in OPT.replacements()['src/nx/gpu/vk/pipeline.c']:
            self.assertEqual(source.count(old), 1)
            source = source.replace(old, new, 1)
        start = source.index('static void pf_start_load(void) {')
        end = source.index('\n}\n', start) + 3
        function = source[start:end]
        program = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
static struct {
    struct { int lock; } file;
    int lock, done, on;
    char path[1200];
} g_pf;
static struct { int shader_captures; } g_settings;
static int snx_ryu_persistent, threads, null_modules, synchronous_loads;
static char g_cache_dir[1024];
static const char* g_exename = "01006BB00C6F0000";
#define LOG(...) printf(__VA_ARGS__)
static void pm_init(int* p) { *p = 0; }
static void pc_init(int* p) { *p = 0; }
static void null_fs(void) { null_modules++; }
static void pf_load(void* arg) { (void)arg; synchronous_loads++; }
static int plat_thread(void (*fn)(void*), void* arg, size_t stack) {
    (void)fn; (void)arg; (void)stack; threads++; return 0;
}
static int snx_ryu_cache_path(char* out, size_t cap, const char* dir, const char* game, const char* ext) {
    int n = snprintf(out, cap, "%s/%s.test%s", dir, game, ext);
    return n >= 0 && (size_t)n < cap;
}
''' + function + r'''
int main(int argc, char** argv) {
    assert(argc == 2);
    snprintf(g_cache_dir, sizeof g_cache_dir, "%s", argv[1]);
    unsetenv("SNX_SHADER_CORPUS"); unsetenv("SNX_RYUJINX_NATIVE_PROBE");
    pf_start_load();
    assert(g_pf.on && threads == 1 && null_modules == 1 && !synchronous_loads);
    assert(strstr(g_pf.path, "01006BB00C6F0000.vkshaders"));
    g_pf.on = 0; g_settings.shader_captures = 1;
    pf_start_load(); /* Android --diag=1 capture, even with an existing cache */
    assert(!g_pf.on && threads == 1 && null_modules == 1);
    g_settings.shader_captures = 0; setenv("SNX_SHADER_CORPUS", "private-corpus", 1);
    pf_start_load();
    assert(!g_pf.on && threads == 1 && null_modules == 1);
    unsetenv("SNX_SHADER_CORPUS");
    pf_start_load(); /* disabling capture restores the original prewarm */
    assert(g_pf.on && threads == 2 && null_modules == 2);
    g_pf.on = 0; g_settings.shader_captures = 1;
    setenv("SNX_RYUJINX_NATIVE_PROBE", "1", 1); snx_ryu_persistent = 1;
    pf_start_load();
    assert(!g_pf.on && threads == 2 && null_modules == 2);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shader_file = root / '01006BB00C6F0000.vkshaders'
            shader_file.write_bytes(b'existing shader records')
            output = compile_run(program, root, root)
            self.assertEqual(shader_file.read_bytes(), b'existing shader records')
            self.assertEqual(output.count('SNX_SHADER_CAPTURE_V1'), 3)

    @unittest.skipUnless((SRC / '.git').exists() and shutil.which('cc'), 'pinned source and C compiler required')
    def test_original_pipeline_file_corruption_and_reopen_regressions(self):
        # Keep every upstream assertion and the real PfShader/ShaderInfo. Inject
        # ENOSPC at the I/O boundary: Android /dev/full may be inaccessible or
        # behave differently from the Linux host. No runtime source is patched.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'snx_settings.h').write_text('/* this test reads no generated settings */\n')
            binary = root / 'pipeline-file'
            command = ['cc', '-std=gnu11', '-D_GNU_SOURCE', '-DSNX_VK_H', '-ffunction-sections',
                       '-fdata-sections', '-Wall', '-Wextra', '-I' + str(root), '-I' + str(SRC / 'src'),
                       str(SRC / 'tests/pipeline_file.c'), str(SRC / 'src/common/filesystem/host.c'),
                       str(SRC / 'src/common/utilities/common.c'),
                       str(ROOT / 'tests/fixtures/zelda_pipeline_enospc.c'),
                       '-Wl,--wrap=fopen,--wrap=fwrite,--wrap=fflush,--wrap=fclose',
                       '-Wl,--gc-sections', '-pthread', '-o', str(binary)]
            build = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode in ('write', 'flush'):
                with self.subTest(enospc_at=mode):
                    run = subprocess.run([str(binary)], cwd=root, capture_output=True, text=True,
                                         env={**os.environ, 'SNX_TEST_ENOSPC_MODE': mode})
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertIn('74 checks passed', run.stdout)
                    # Prove that this check ran, rather than being skipped or
                    # satisfied by the host's real /dev/full implementation.
                    self.assertEqual(run.stderr.count('SNX_TEST_ENOSPC_INJECTED=' + mode), 1, run.stderr)


if __name__ == '__main__':
    unittest.main()
