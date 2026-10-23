"""Execute bounded graphics diagnostics without a Vulkan driver or game assets."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GraphicsDiagnosticsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_opt_in_resource_decisions_deduplication_bounds_and_window_reset(self):
        program = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
typedef uint64_t u64;
typedef uint32_t u32;
typedef unsigned VkImageViewType;
typedef uint64_t VkImageView;
#define VK_NULL_HANDLE 0
#define VK_IMAGE_VIEW_TYPE_2D 1
typedef struct { int shadow; } ShTex;
typedef struct { u64 hash; struct { u64 tex_dc_color_mask; } si; } VkSh;
typedef struct {
    u64 gva; u32 w, h;
    struct { int vk, is_int, sint, depth; } f;
} Surf;
static struct { int shadows; } g_settings = {1};
static u32 g_vk_present = 10;
static int snx_perf_on;
static int vk_tic_reads_stencil(const u32* tic) { return tic[0] == 1234; }
#define LOG(...) printf(__VA_ARGS__)
#include "gfx_diag.h"
int main(void) {
    VkSh vs = {.hash = 100}, fs = {.hash = 200};
    Surf depth = {.gva = 4096, .w = 1024, .h = 1024, .f = {.vk = 124, .depth = 1}};
    Surf color = {.gva = 8192, .w = 1280, .h = 720, .f = {.vk = 37}};
    Surf* rt[8] = {0};
    u32 r[0xE00] = {0}, tic[8] = {0}, tsc[8] = {0};
    ShTex shadow = {1}, plain = {0};
    r[0x4B3] = r[0x4BA] = 1; r[0x4C3] = 0x203;
    setenv("SNX_GFX_DIAG", "1", 1);
    snx_gfx_init(); assert(!snx_gfx_diag_on); /* measurement OFF wins */
    snx_gfx_draw(&vs, &fs, rt, &depth, 0, r);
    snx_gfx_texture(&fs, 4, 0, &shadow, 0, tic, tsc, &depth, 1, 0, 1, 0);
    assert(!snx_gfx_counts[SNX_GFX_SETUPS] && !snx_gfx_counts[SNX_GFX_BINDINGS]);
    snx_perf_on = 1; unsetenv("SNX_GFX_DIAG"); snx_gfx_init(); assert(!snx_gfx_diag_on);
    setenv("SNX_GFX_DIAG", "0", 1); snx_gfx_init(); assert(!snx_gfx_diag_on);
    setenv("SNX_GFX_DIAG", "1", 1); snx_gfx_init(); assert(snx_gfx_diag_on);
    Surf original = depth;
    snx_gfx_draw(&vs, &fs, rt, &depth, 0, r);
    snx_gfx_draw(&vs, &fs, rt, &depth, 0, r); /* same detail, two attempts */
    rt[0] = &color;
    snx_gfx_draw(&vs, NULL, rt, &depth, 1, r);
    snx_gfx_texture(&fs, 4, 0, &shadow, 0, tic, tsc, &depth, 1, 0, 1, 0);
    snx_gfx_texture(&fs, 4, 0, &shadow, 0, tic, tsc, &depth, 1, 0, 1, 0);
    snx_gfx_texture(&fs, 4, 1, &shadow, 77, tic, tsc, NULL, 1, 0, 0, 0);
    snx_gfx_texture(&fs, 4, 1, &shadow, 77, tic, tsc, NULL, 1, 0, 0, 0);
    /* Plain depth comparisons use a color view intentionally. */
    fs.si.tex_dc_color_mask = 1;
    snx_gfx_texture(&fs, 4, 0, &shadow, 1, tic, tsc, &color, 1, 0, 1, 0);
    fs.si.tex_dc_color_mask = 0;
    snx_gfx_texture(&fs, 4, 0, &shadow, 1, tic, tsc, &color, 1, 0, 1, 0);
    color.f.is_int = 1;
    snx_gfx_texture(&fs, 4, 2, &plain, 2, tic, tsc, &color, 1, 0, 0, 0);
    color.f.is_int = 0;
    snx_gfx_texture(&fs, 4, 3, &plain, 3, tic, tsc, &color, 3, 0, 1, 1);
    /* Same-type surface whose view could not be made. */
    snx_gfx_texture(&fs, 4, 4, &plain, 4, tic, tsc, &color, 3, 0, 0, 0);
    /* Ordinary valid 2D textures count, but need no detail. */
    snx_gfx_texture(&fs, 4, 5, &plain, 5, tic, tsc, &color, 1, 0, 1, 0);
    assert(!memcmp(&depth, &original, sizeof depth));
    assert(r[0x4B3] == 1 && r[0x4BA] == 1 && r[0x4C3] == 0x203);
    snx_gfx_report(1); snx_gfx_report(2);
    for (unsigned i = 0; i < 200; i++) {
        fs.hash = 1000 + i;
        snx_gfx_draw(&vs, &fs, rt, &depth, 1, r);
        snx_gfx_texture(&fs, 4, 0, &shadow, i, tic, tsc, NULL, 1, 0, 0, 1);
    }
    assert(snx_gfx_pass_n == SNX_GFX_PASS_CAP && snx_gfx_bind_n == SNX_GFX_BIND_CAP);
    snx_gfx_report(3);
    assert(!snx_gfx_pass_n && !snx_gfx_bind_n);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, binary = root / 'gfx.c', root / 'gfx'
            source.write_text(program)
            subprocess.run(['cc', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra',
                            '-Werror', '-I' + str(ROOT / 'tools/zelda-perf'), str(source), '-o', str(binary)],
                           check=True, capture_output=True, text=True)
            output = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
        rows = [(line.split(' ', 1)[0], json.loads(line.split(' ', 1)[1])) for line in output.splitlines()]
        self.assertTrue(all(len(line.encode()) < 2048 for line in output.splitlines()))
        self.assertEqual(sum(k == 'SNX_GFX_META_V1' for k, r in rows), 1)
        self.assertEqual(sum(k == 'SNX_GFX_PASS_V1' for k, r in rows), 66)
        self.assertEqual(sum(k == 'SNX_GFX_BIND_V1' for k, r in rows), 135)
        self.assertEqual(sum(k == 'SNX_GFX_LIMIT_V1' for k, r in rows), 2)
        windows = {r['window']: r for k, r in rows if k == 'SNX_GFX_V1'}
        self.assertEqual(windows[1], {
            'window': 1, 'draw_setups': 3, 'depth_only_setups': 2, 'binding_events': 10,
            'null_bindings': 4, 'shadow_bindings': 6, 'null_shadow_bindings': 2,
            'indexed_entries': 1, 'shadow_color_views': 1})
        self.assertTrue(all(v == 0 for k, v in windows[2].items() if k != 'window'))
        self.assertEqual(windows[3]['draw_setups'], 200)
        self.assertEqual(windows[3]['null_shadow_bindings'], 200)
        bindings = [r for k, r in rows if k == 'SNX_GFX_BIND_V1']
        self.assertTrue(any(r['handle'] == '00000000' and r['bound'] for r in bindings))
        self.assertEqual({r['reason'] for r in bindings},
                         {'real_view', 'surface_unavailable', 'numeric_kind', 'view_unavailable'})


if __name__ == '__main__':
    unittest.main()
