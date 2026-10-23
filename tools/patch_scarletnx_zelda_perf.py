#!/usr/bin/env python3
"""Opt-in telemetry on pinned ScarletNX 34853ee; transactional and reversible.

No clock, shader, synchronization, AOT or image semantics are changed here.
Apply after the translator patch and restore before restoring that patch.
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
INC = '#include "nx/runtime/snx_perf.h"'

VK_SNAPSHOT = r'''
/* Window deltas; these count recorded work, not physically displayed frames. */
static void snx_perf_vk_snapshot(u64 window) {
    static u64 was[20];
    u64 v[20], made, hits, left;
    vk_pipeline_stats(&v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);
    vk_tex_stats(&v[6], &v[7]);
    v[8] = g_vk_drawn; v[9] = g_vk_skipped;
    v[10] = g_rec_buf_bytes; v[11] = g_rec_xfers; v[12] = g_rec_barriers;
    v[13] = g_vk_dset_new; v[14] = g_vk_dset_reused;
    v[15] = g_vk_rt_readbacks; v[16] = g_vk_rt_copies; v[17] = vk_rt_made();
    v[18] = g_vk_finishes; v[19] = g_vk_dispatches;
    vk_pipeline_prewarm_stats(&made, &hits, &left);
    const char* names[20] = {"pipelines", "pipeline_hits", "pipeline_make_ms", "pipeline_wait_ms",
        "shaders", "shader_ms", "uploads", "upload_bytes", "draws", "skipped_draws", "copy_bytes",
        "copies", "barriers", "descriptor_new", "descriptor_reused", "rt_readbacks", "feedback_copies",
        "rt_created", "finishes", "dispatches"};
    char line[1400];
    size_t n = (size_t)snprintf(line, sizeof line, "SNX_VK_V1 {\"window\":%llu", (unsigned long long)window);
    for (int i = 0; i < 20; i++) {
        n += (size_t)snprintf(line + n, sizeof line - n, ",\"%s\":%llu", names[i],
                             (unsigned long long)(v[i] - was[i]));
        was[i] = v[i];
    }
    snprintf(line + n, sizeof line - n, ",\"prewarm_made\":%llu,\"prewarm_left\":%llu}",
             (unsigned long long)made, (unsigned long long)left);
    LOG("%s\n", line);
}
'''


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('#define VK_FRAMES 2  /* frames in flight */', INC + '\n#define VK_FRAMES 2  /* frames in flight */'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('static VkSemaphore g_acquired[VK_FRAMES];',
             '#include "nx/runtime/snx_perf_impl.h"\n' + VK_SNAPSHOT + '\nstatic VkSemaphore g_acquired[VK_FRAMES];'),
            ('    if (!vk_init()) return 0;', '    snx_perf_init();\n    if (!vk_init()) return 0;'),
            ('static void show(Surf* src, u32 fw, u32 fh, u32 transform, int game) {',
             'static void show(Surf* src, u32 fw, u32 fh, u32 transform, int game) {\n'
             '    u64 snx_show_t0 = game && snx_perf_on ? plat_ns() : 0;'),
            ('        VkResult r = vkAcquireNextImageKHR(g_vk.dev, g_vk.swapchain, 0, acq, VK_NULL_HANDLE, &idx);',
             '        u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '        VkResult r = vkAcquireNextImageKHR(g_vk.dev, g_vk.swapchain, 0, acq, VK_NULL_HANDLE, &idx);\n'
             '        if (snx_perf_on && game) {\n'
             '            snx_perf_add(SNX_PM_ACQUIRE, plat_ns() - snx_t0, 1);\n'
             '            if (r == VK_NOT_READY || r == VK_TIMEOUT) snx_perf_add(SNX_PM_NO_IMAGE, 0, 1);\n'
             '        }'),
            ('        VkResult r = vkQueuePresentKHR(g_vk.gfx, &pi);',
             '        u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '        VkResult r = vkQueuePresentKHR(g_vk.gfx, &pi);\n'
             '        if (snx_perf_on && game) {\n'
             '            snx_perf_add(SNX_PM_PRESENT, plat_ns() - snx_t0, 1);\n'
             '            if (r == VK_SUCCESS || r == VK_SUBOPTIMAL_KHR) snx_perf_frame(SNX_PF_PRESENT);\n'
             '        }'),
            ('        g_vk.sc_lost = 0;\n        g_lost = 1;\n    }\n}',
             '        g_vk.sc_lost = 0;\n        g_lost = 1;\n    }\n'
             '    if (game && snx_perf_on) {\n'
             '        snx_perf_add(SNX_PM_RENDER_CPU, plat_ns() - snx_show_t0, 1);\n'
             '        u64 window = snx_perf_frame(SNX_PF_RENDER);\n'
             '        if (window) snx_perf_vk_snapshot(window);\n    }\n}'),
        ],
        'src/nx/gpu/vk/cmd.c': [
            ('static void timeline_wait(u64 value) {',
             'static void timeline_wait(u64 value) {\n    u64 snx_t0 = snx_perf_on ? plat_ns() : 0;'),
            ('    VK_OK(vkWaitSemaphores(g_vk.dev, &wi, UINT64_MAX));',
             '    VK_OK(vkWaitSemaphores(g_vk.dev, &wi, UINT64_MAX));\n'
             '    if (snx_perf_on) snx_perf_add(SNX_PM_TIMELINE, plat_ns() - snx_t0, 1);'),
            ('        timeline_wait(done);\n        land_through(done);',
             '        u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '        timeline_wait(done);\n'
             '        if (snx_perf_on) snx_perf_add(SNX_PM_RECYCLE, plat_ns() - snx_t0, 1);\n'
             '        land_through(done);'),
        ],
        'src/nx/gpu/vk/record.c': [
            ('    publish();\n    while (__atomic_load_n(&g_tail, __ATOMIC_ACQUIRE) != g_pending) plat_yield();',
             '    u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '    publish();\n    while (__atomic_load_n(&g_tail, __ATOMIC_ACQUIRE) != g_pending) plat_yield();\n'
             '    if (snx_perf_on) snx_perf_add(SNX_PM_RECORD_SYNC, plat_ns() - snx_t0, 1);'),
            ('    VkResult r = vkQueueSubmit2(g_vk.gfx, 1, &si, VK_NULL_HANDLE);',
             '    u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '    VkResult r = vkQueueSubmit2(g_vk.gfx, 1, &si, VK_NULL_HANDLE);\n'
             '    if (snx_perf_on) snx_perf_add(SNX_PM_SUBMIT, plat_ns() - snx_t0, 1);'),
        ],
        'src/nx/gpu/vk/texture.c': [
            ('static int tex_upload(Surf* t) {', 'static int snx_tex_upload_raw(Surf* t) {'),
            ('/* change checks: a hash of the whole texture, 4 KiB at a time, the same whichever way its bytes are reached (the',
             'static int tex_upload(Surf* t) {\n'
             '    u64 t0 = snx_perf_on ? plat_ns() : 0;\n'
             '    int ok = snx_tex_upload_raw(t);\n'
             '    if (snx_perf_on) snx_perf_add(SNX_PM_TEX_UPLOAD, plat_ns() - t0, 1);\n'
             '    return ok;\n}\n\n'
             '/* change checks: a hash of the whole texture, 4 KiB at a time, the same whichever way its bytes are reached (the'),
            ('static u64 mem_hash(u64 gva, u64 size) {', 'static u64 snx_mem_hash_raw(u64 gva, u64 size) {'),
            ("/* the texture's memory hashed again, and loaded again when that changed: 1 if it did */",
             'static u64 mem_hash(u64 gva, u64 size) {\n'
             '    u64 t0 = snx_perf_on ? plat_ns() : 0;\n'
             '    u64 hash = snx_mem_hash_raw(gva, size);\n'
             '    if (snx_perf_on) {\n'
             '        snx_perf_add(SNX_PM_TEX_HASH, plat_ns() - t0, 1);\n'
             '        snx_perf_add(SNX_PM_HASH_BYTES, 0, size);\n    }\n'
             '    return hash;\n}\n\n'
             "/* the texture's memory hashed again, and loaded again when that changed: 1 if it did */"),
        ],
        'src/nx/hle/services/vi.c': [
            ('#include "nx/hle/services/vi.h"', '#include "nx/hle/services/vi.h"\n' + INC),
            ('                qslot = slot;\n                qkey = vi_key(li, slot);',
             '                qslot = slot;\n                qkey = vi_key(li, slot);\n'
             '                if (li == VI_SHOWN && snx_perf_on) snx_perf_frame(SNX_PF_GUEST);'),
        ],
        'src/nx/runtime/present.c': [
            ('#include "nx/runtime/main.h"', '#include "nx/runtime/main.h"\n' + INC),
            ('    if (next > now) plat_sleep_ns((i64)(next - now));',
             '    if (next > now) {\n        u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '        plat_sleep_ns((i64)(next - now));\n'
             '        if (snx_perf_on) snx_perf_add(SNX_PM_PACE, plat_ns() - snx_t0, 1);\n    }'),
        ],
        'src/nx/runtime/guest_jit.c': [
            ('#include "nx/runtime/guest_jit.h"', '#include "nx/runtime/guest_jit.h"\n' + INC),
            ('static void jit_log(const SnxJitReport* r) {',
             'static void jit_log(const SnxJitReport* r) {\n'
             '    if (snx_perf_on) snx_perf_add(r->error || r->dropped ? SNX_PM_JIT_FAILED : SNX_PM_JIT_COMPILE,\n'
             '                                  (u64)(r->seconds * 1e9), 1);'),
            ('GuestFn jit_wait(u64 pc) { return g_jit ? snx_jit_wait(g_jit, pc) : NULL; }',
             'GuestFn jit_wait(u64 pc) {\n    u64 snx_t0 = snx_perf_on ? plat_ns() : 0;\n'
             '    GuestFn fn = g_jit ? snx_jit_wait(g_jit, pc) : NULL;\n'
             '    if (snx_perf_on) snx_perf_add(SNX_PM_JIT_WAIT, plat_ns() - snx_t0, 1);\n'
             '    return fn;\n}'),
        ],
    }


def apply(root, revision='', revert=False):
    updated = {}
    for name, pairs in replacements().items():
        path = root / name
        text = path.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            source, target = (new, old) if revert else (old, new)
            if not revert and text.count(new) == 1:
                continue
            if revert and new not in text and text.count(old) == 1:
                continue
            if text.count(source) != 1:
                raise ValueError('unknown pinned source; no files changed: ' + name + ': ' + source[:65])
            text = text.replace(source, target, 1)
        updated[path] = text
    # All source anchors must match before the first write.
    for path, text in updated.items():
        if path.read_text() != text:
            path.write_text(text)
    dest = root / 'src/nx/runtime'
    for source, target in [('perf.h', 'snx_perf.h'), ('perf_impl.h', 'snx_perf_impl.h')]:
        path = dest / target
        if revert:
            path.unlink(missing_ok=True)
        else:
            content = (HERE / 'zelda-perf' / source).read_bytes()
            if not path.exists() or path.read_bytes() != content:
                path.write_bytes(content)
    path = dest / 'snx_perf_build.h'
    if revert:
        path.unlink(missing_ok=True)
    else:
        content = '#define SNX_PERF_REVISION ' + json.dumps(revision) + '\n'
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
    print('Zelda performance telemetry:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--revision', default='')
    p.add_argument('--revert', action='store_true')
    a = p.parse_args()
    apply(a.source, a.revision, a.revert)
