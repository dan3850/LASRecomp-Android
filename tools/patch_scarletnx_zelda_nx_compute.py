#!/usr/bin/env python3
"""Port nxnative/Ryujinx buffer compute and its own validated persistent cache.

Apply after the complete Zelda performance/depth stack, restore before it.
No game hashes, host-memory aliases, synchronization or CPU policy changes.
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replacements():
    return {
        'src/nx/gpu/vk/vk.h': [
            ('void snx_d24_pack_report(u64 window);',
             'void snx_d24_pack_report(u64 window);\n'
             'int snx_nx_compute_enabled(void);\nvoid snx_nx_compute_init(void);\n'
             'void snx_nx_compute_report(u64 window);\n'
             'u32* snx_nx_compute_spirv(const u8* code, u32 len, ShaderInfo* si, size_t* words,\n'
             '                          const u8* c1, u32 c1n);'),
        ],
        'src/nx/gpu/vk/pipeline.c': [
            ('static VkPipelineCache g_pcache;',
             'static VkPipelineCache g_pcache;\n#include "nx/gpu/vk/snx_nx_compute.h"'),
            ('void vk_pipeline_init(void) {',
             'void vk_pipeline_init(void) {\n    snx_nx_compute_init();'),
            ('    /* the temporary name is the process\'s own: two games running at once would otherwise write the same file */',
             '    snx_nx_driver_path(g_pcache_path, sizeof g_pcache_path);\n'
             '    /* the temporary name is the process\'s own: two games running at once would otherwise write the same file */'),
        ],
        'src/nx/gpu/vk/compute.c': [
            ('static CsPipe* g_csp[256];',
             'static CsPipe* g_csp[256];\n'
             'static u64 g_nx_c1_snapshot_bytes;\n'
             '#define SNX_NX_C1_SNAPSHOT_CAP (16ull << 20)'),
            ('    VkCbReads cbr; /* the constant buffer words translation read */',
             '    VkCbReads cbr; /* the constant buffer words translation read */\n'
             '    u8* nx_c1; /* exact compile-time driver constant segment, immutable */\n'
             '    u32 nx_c1_bytes;'),
            ('    while (p && (p->key != key || !vk_cb_reads_hold(&p->cbr, cs_cb_read))) p = p->next;',
             '    while (p && (p->key != key || !vk_cb_reads_hold(&p->cbr, cs_cb_read) ||\n'
             '           (p->nx_c1 && (p->nx_c1_bytes != g_cbn[1] ||\n'
             '             memcmp(p->nx_c1, g_cb[1], p->nx_c1_bytes))))) p = p->next;'),
            ('    u32* spv = vk_translate_spirv(code, 0x10000 + 80, ST_CS, &p->si, &nw, cs_cb_read, &p->cbr);',
             '    ShaderInfo snx_nx_native_key = p->si;\n'
             '    int snx_nx_backend = 0;\n'
             '    u32* spv = NULL;\n'
             '    if (snx_nx_compute_enabled()) {\n'
             '        /* Keep failed-attempt dependencies too: a later valid C1\n'
             '           must retry the port instead of reusing a native fallback. */\n'
             '        u32 snapshot_bytes = g_cbn[1] ? g_cbn[1] : 1;\n'
             '        if (snapshot_bytes <= sizeof g_cb[1] &&\n'
             '            g_nx_c1_snapshot_bytes <= SNX_NX_C1_SNAPSHOT_CAP - snapshot_bytes)\n'
             '            p->nx_c1 = malloc(snapshot_bytes);\n'
             '        if (p->nx_c1) {\n'
             '            g_nx_c1_snapshot_bytes += snapshot_bytes;\n'
             '            p->nx_c1_bytes = g_cbn[1];\n'
             '            memcpy(p->nx_c1, g_cb[1], g_cbn[1]);\n'
             '            spv = snx_nx_compute_spirv(code, blen, &p->si, &nw, g_cb[1], g_cbn[1]);\n'
             '            snx_nx_backend = spv != NULL;\n'
             '        }\n'
             '    }\n'
             '    if (!spv) spv = vk_translate_spirv(code, 0x10000 + 80, ST_CS, &p->si, &nw, cs_cb_read, &p->cbr);\n'
             'snx_nx_create:\n'),
            ('    if (!ok) {\n        p->failed = 1;\n        return p;\n    }\n    VkComputePipelineCreateInfo ci',
             '    if (!ok) {\n'
             '        if (snx_nx_backend) goto snx_nx_retry_native;\n'
             '        p->failed = 1;\n        return p;\n    }\n    VkComputePipelineCreateInfo ci'),
            ('    vkDestroyShaderModule(g_vk.dev, m, NULL);\n    if (!p->failed)',
             '    vkDestroyShaderModule(g_vk.dev, m, NULL);\n'
             '    if (p->failed && snx_nx_backend) goto snx_nx_retry_native;\n'
             '    if (snx_nx_compute_enabled() && !p->failed)\n'
             '        LOG_LIMIT(12, "SNX_NX_COMPUTE_PIPELINE_V1 selected=%s key=%016llx\\n",\n'
             '                  snx_nx_backend ? "nxnative" : "scarlet", (unsigned long long)key);\n'
             '    if (!p->failed)'),
            ('                  (unsigned long long)key, lx, ly, lz, p->si.ngbuf, p->si.ntex, p->si.nimg);\n'
             '    return p;\n}',
             '                  (unsigned long long)key, lx, ly, lz, p->si.ngbuf, p->si.ntex, p->si.nimg);\n'
             '    return p;\n'
             'snx_nx_retry_native:\n'
             '    WARN("SNX_NX_COMPUTE_PIPELINE_V1 driver rejected port; retry native key=%016llx\\n",\n'
             '         (unsigned long long)key);\n'
             '    snx_nx_backend = 0; p->failed = 0; p->si = snx_nx_native_key;\n'
             '    spv = vk_translate_spirv(code, 0x10000 + 80, ST_CS, &p->si, &nw, cs_cb_read, &p->cbr);\n'
             '    goto snx_nx_create;\n}'),
        ],
        'src/nx/gpu/vk/renderer.c': [
            ('snx_d24_pack_report(window); }', 'snx_d24_pack_report(window); snx_nx_compute_report(window); }'),
        ],
    }


def apply(root, revert=False):
    changes = {}
    for name, pairs in replacements().items():
        path = root / name
        text = path.read_text()
        for old, new in reversed(pairs) if revert else pairs:
            if (not revert and text.count(new) == 1) or (revert and new not in text and text.count(old) == 1):
                continue
            before, after = (new, old) if revert else (old, new)
            if text.count(before) != 1:
                raise ValueError('Unknown nxnative compute source; no changes: ' + name)
            text = text.replace(before, after, 1)
        changes[path] = text
    headers = {}
    for name in ['nx_compute.h', 'nx_compute_adapter.h']:
        path = root / 'src/nx/gpu/vk' / ('snx_' + name)
        data = (HERE / 'zelda-perf' / name).read_bytes()
        if path.exists() and path.read_bytes() != data:
            raise ValueError('Unknown nxnative compute header; no changes: ' + name)
        headers[path] = data
    for path, text in changes.items():
        if path.read_text() != text:
            path.write_text(text)
    for path, data in headers.items():
        if revert:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)
    print('nxnative/Ryujinx Vulkan buffer compute and cache:', 'RESTORED' if revert else 'INSTALLED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revert', action='store_true')
    args = parser.parse_args()
    apply(args.source, args.revert)
