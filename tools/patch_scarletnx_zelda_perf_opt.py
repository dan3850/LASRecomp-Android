#!/usr/bin/env python3
"""Two opt-in experiments after the telemetry and ABI 1 live adapter patches.

No shader format, draw, GPU barrier, readback, AOT or guest clock is removed.
This deliberately refuses ABI 2: its extra facts are not in PfShader.
"""
import argparse
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
LIVE = runpy.run_path(str(HERE / 'ryujinx-nativeaot/patch_scarletnx_live_probe.py'))
CACHE = LIVE['CACHE_NEW']
CACHE_PERSIST = CACHE.replace('if (ryu && !strcmp(ryu, "1")) {',
                             'if (ryu && !strcmp(ryu, "1") && !snx_ryu_persistent) {')
CACHE_PERSIST = CACHE_PERSIST.replace('if (getenv("SNX_SHADER_CORPUS")) {',
                                      'if (getenv("SNX_SHADER_CORPUS") || g_settings.shader_captures) {')
CACHE_PERSIST = CACHE_PERSIST.replace(
    'vulkan: SNX_SHADER_CORPUS is set, so every shader is translated and none is kept for the next run',
    'vulkan: SNX_SHADER_CAPTURE_V1 capture enabled; translated-shader persistence bypassed, existing files untouched')


def replacements():
    return {
        'src/nx/gpu/vk/cmd.c': [
            ('#include "nx/runtime/platform/plat.h"',
             '#include "nx/runtime/platform/plat.h"\n#include "nx/gpu/vk/snx_known_complete.h"'),
            ('void vk_cmd_init(void) {', 'void vk_cmd_init(void) {\n    snx_known_init();'),
            ('static void timeline_wait(u64 value) {',
             'static void timeline_wait(u64 value) {\n'
             '    if (snx_known_ready(value)) {\n'
             '        if (snx_perf_on) snx_perf_add(SNX_PM_WAIT_ELIDED, 0, 1);\n'
             '        return;\n    }'),
            ('    VK_OK(vkWaitSemaphores(g_vk.dev, &wi, UINT64_MAX));',
             '    VkResult snx_wait_result = vkWaitSemaphores(g_vk.dev, &wi, UINT64_MAX);\n'
             '    if (VK_OK(snx_wait_result)) snx_known_note(value);'),
        ],
        'src/nx/gpu/vk/pipeline.c': [
            (LIVE['INCLUDE_NEW'], LIVE['INCLUDE_NEW'] + '\n#include "nx/gpu/vk/snx_ryu_cache.h"'),
            ('    snprintf(g_cache_dir, sizeof g_cache_dir, "%sshader_cache", g_cachedir);\n'
             '    plat_mkdir(g_cache_dir);',
             '    snprintf(g_cache_dir, sizeof g_cache_dir, "%sshader_cache", g_cachedir);\n'
             '    plat_mkdir(g_cache_dir);\n'
             '    /* Keep the working APK\'s shader AND driver files untouched. */\n'
             '    snprintf(g_cache_dir, sizeof g_cache_dir, "%sshader_cache/fps-audit-v1", g_cachedir);\n'
             '    plat_mkdir(g_cache_dir);'),
            ('    snprintf(g_pcache_path, sizeof g_pcache_path, "%s/vk_pipelines.bin", g_cache_dir);',
             '    snx_ryu_cache_setup(strlen(g_cache_dir), strlen(g_exename), sizeof g_pcache_path);\n'
             '    if (snx_ryu_persistent && !snx_ryu_cache_path(g_pcache_path, sizeof g_pcache_path,\n'
             '            g_cache_dir, g_exename, ".vkpipelines")) snx_ryu_persistent = 0;\n'
             '    if (!snx_ryu_persistent)\n'
             '        snprintf(g_pcache_path, sizeof g_pcache_path, "%s/vk_pipelines.bin", g_cache_dir);'),
            ('    PFileMap data;\n    if (!plat_file_map(&data, g_pcache_path) && data.data) {',
             '    PFileMap data = {0};\n'
             '    if ((!snx_ryu_requested() || snx_ryu_persistent) &&\n'
             '        !plat_file_map(&data, g_pcache_path) && data.data) {'),
            ('void vk_pipeline_save(void) {\n    pm_lock(&g_psave);',
             'void vk_pipeline_save(void) {\n'
             '    if (snx_ryu_requested() && !snx_ryu_persistent) return;\n'
             '    pm_lock(&g_psave);'),
            (CACHE, CACHE_PERSIST),
            ('    snprintf(g_pf.path, sizeof g_pf.path, "%s/%s.vkshaders", g_cache_dir, g_exename);',
             '    if (snx_ryu_persistent) {\n'
             '        if (!snx_ryu_cache_path(g_pf.path, sizeof g_pf.path, g_cache_dir, g_exename, ".vkshaders")) {\n'
             '            g_pf.on = 0;\n            return;\n        }\n    } else\n'
             '        snprintf(g_pf.path, sizeof g_pf.path, "%s/%s.vkshaders", g_cache_dir, g_exename);'),
        ],
    }


def apply(root, revert=False):
    updated = {}
    for name, pairs in replacements().items():
        path = root / name
        text = path.read_text()
        if 'snx_rn_try_v2' in text:
            raise ValueError('ABI 2 is not supported by the ABI 1 cache experiment')
        for old, new in reversed(pairs) if revert else pairs:
            if not revert and text.count(new) == 1:
                continue
            if revert and new not in text and text.count(old) == 1:
                continue
            source, target = (new, old) if revert else (old, new)
            if text.count(source) != 1:
                raise ValueError('unknown pinned source; no files changed: ' + name + ': ' + source[:65])
            text = text.replace(source, target, 1)
        updated[path] = text
    for path, text in updated.items():
        if path.read_text() != text:
            path.write_text(text)
    dest = root / 'src/nx/gpu/vk'
    for name in ['known_complete', 'ryu_cache']:
        path = dest / ('snx_' + name + '.h')
        if revert:
            path.unlink(missing_ok=True)
        else:
            data = (HERE / 'zelda-perf' / (name + '.h')).read_bytes()
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
    print('Zelda confirmed-completion/isolated-v1-cache experiments:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--revert', action='store_true')
    a = p.parse_args()
    apply(a.source, a.revert)
