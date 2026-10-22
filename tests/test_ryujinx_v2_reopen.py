"""Execute the injected cache guards across cold/reopened ABI 2 sessions."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('patch_v2', ROOT / 'tools/ryujinx-nativeaot/patch_runtime_v2.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


class ReopenCacheTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required for cache guard regression')
    def test_existing_cache_is_never_read_or_overwritten_in_abi2(self):
        pairs = patch.replacements()['src/nx/gpu/vk/pipeline.c']
        load = next(new for old, new in pairs if 'PFileMap data;' in old)
        save = next(new for old, new in pairs if old.startswith('void vk_pipeline_save'))
        program = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define LOG(...) ((void)0)
typedef struct { void *data; size_t size; } PFileMap;
static int enabled, reads, writes, locks, unmaps;
static int g_psave;
static char saved[] = "existing cache, preserved";
static const char *g_pcache_path = "unused";
static int snx_rn_enabled(void) { return enabled; }
static int plat_file_map(PFileMap *map, const char *path) {
    (void)path; reads++; map->data = saved; map->size = sizeof saved; return 0;
}
static void plat_file_unmap(PFileMap *map) {
    unmaps++; if (!map->data) assert(map->size == 0);
}
static void pm_lock(int *p) { (void)p; locks++; }
static size_t initial_size;
static void load_session(void) {
    struct { size_t initialDataSize; const void *pInitialData; } ci = {0};
''' + load + r'''
        ci.initialDataSize = data.size;
        ci.pInitialData = data.data;
    }
    initial_size = ci.initialDataSize;
    if (enabled) assert(ci.pInitialData == NULL);
    plat_file_unmap(&data);
}
''' + save + r'''
    writes++;
}
int main(void) {
    enabled = 1;
    for (int session = 0; session < 3; session++) {
        load_session(); vk_pipeline_save();
        assert(initial_size == 0 && reads == 0 && writes == 0 && locks == 0);
        assert(!strcmp(saved, "existing cache, preserved"));
    }
    enabled = 0; load_session(); vk_pipeline_save();
    assert(initial_size == sizeof saved && reads == 1 && writes == 1 && locks == 1);
    assert(unmaps == 4);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'reopen.c'
            binary = Path(tmp) / 'reopen'
            source.write_text(program)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
