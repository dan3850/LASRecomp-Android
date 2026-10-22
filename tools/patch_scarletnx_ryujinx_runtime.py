#!/usr/bin/env python3
"""Inject a strictly opt-in Ryujinx fragment shader bridge into pinned ScarletNX.

Patch only the experimental build's temporary upstream source. --revert
restores pipeline.c and removes the generated header; no game data in Git.
"""
import argparse
from pathlib import Path

HEADER = "/* Experimental Castlevania Ryujinx native-scale bridge. PRIVATE user-derived pack.\n   Included only by pipeline.c on the experimental branch, not built into Mario.\n   Binary program bytes must match the live Maxwell shader exactly. */\n#ifndef SNX_CASTLEVANIA_RYUJINX_BRIDGE_H\n#define SNX_CASTLEVANIA_RYUJINX_BRIDGE_H\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\nenum { SNX_RB_MIN_COUNT = 5, SNX_RB_MAX_COUNT = 32, SNX_RB_MAX_SPV = 1048576, SNX_RB_MAX_CODE = 65536 };\ntypedef struct {\n    u8 key[16];\n    u32 code_len, spv_len, cbuf_mask, in_mask, out_mask, ntex;\n    u32 off0[64], off1[64];\n    u8* code;\n    u32* spirv;\n} SnxRbEntry;\n\nstatic SnxRbEntry snx_rb_entries[SNX_RB_MAX_COUNT];\nstatic u32 snx_rb_count;\nstatic int snx_rb_initialized;\n\nstatic int snx_rb_read(FILE* file, void* out, size_t size) {\n    return size && fread(out, 1, size, file) == size;\n}\nstatic void snx_rb_forget(void) {\n    for (u32 j = 0; j < SNX_RB_MAX_COUNT; j++) {\n        free(snx_rb_entries[j].code);\n        free(snx_rb_entries[j].spirv);\n    }\n    memset(snx_rb_entries, 0, sizeof snx_rb_entries);\n    snx_rb_count = 0;\n}\nstatic void snx_rb_load(void) {\n    if (snx_rb_initialized) return;\n    snx_rb_initialized = 1;\n    const char* path = getenv(\"SNX_RYUJINX_BRIDGE\");\n    if (!path || !*path) return; /* disabled by default */\n    FILE* f = fopen(path, \"rb\");\n    if (!f) {\n        WARN(\"vulkan: Castlevania Ryujinx pack is absent; using native translator\\n\");\n        return;\n    }\n    u8 magic[8];\n    u32 count = 0;\n    int good = snx_rb_read(f, magic, sizeof magic) && !memcmp(magic, \"SNXRB001\", 8) &&\n               snx_rb_read(f, &count, sizeof count) && count >= SNX_RB_MIN_COUNT && count <= SNX_RB_MAX_COUNT;\n    for (u32 j = 0; good && j < count; j++) {\n        SnxRbEntry* e = &snx_rb_entries[j];\n        good = snx_rb_read(f, e->key, sizeof e->key) &&\n               snx_rb_read(f, &e->code_len, 4) &&\n               snx_rb_read(f, &e->spv_len, 4) &&\n               snx_rb_read(f, &e->cbuf_mask, 4) &&\n               snx_rb_read(f, &e->in_mask, 4) &&\n               snx_rb_read(f, &e->out_mask, 4) &&\n               snx_rb_read(f, &e->ntex, 4);\n        if (!good || e->code_len < 88 || e->code_len > SNX_RB_MAX_CODE ||\n            e->spv_len < 20 || e->spv_len > SNX_RB_MAX_SPV || (e->spv_len & 3) ||\n            e->ntex == 0 || e->ntex > 64 ||\n            (e->cbuf_mask & ~((1u << 18) - 1)) || !e->out_mask || (e->out_mask & ~255u)) {\n            good = 0;\n            break;\n        }\n        for (u32 i = 0; good && i < e->ntex; i++) {\n            good = snx_rb_read(f, &e->off0[i], 4) && snx_rb_read(f, &e->off1[i], 4) &&\n                   e->off0[i] < 16384 && e->off1[i] < 16384;\n        }\n        if (!good) break;\n        e->code = malloc(e->code_len);\n        e->spirv = malloc(e->spv_len);\n        good = e->code && e->spirv && snx_rb_read(f, e->code, e->code_len) &&\n               snx_rb_read(f, e->spirv, e->spv_len) && e->spirv[0] == 0x07230203u &&\n               e->spirv[1] == 0x00010300u;\n    }\n    if (good) good = fgetc(f) == EOF;\n    fclose(f);\n    if (!good) {\n        snx_rb_forget();\n        WARN(\"vulkan: rejected Castlevania Ryujinx pack; native translator preserved\\n\");\n        return;\n    }\n    snx_rb_count = count;\n    WARN(\"vulkan: experimental Castlevania Ryujinx bridge loaded: %u private shaders\\n\", count);\n}\n\n/* NULL means no exact match or opt-in disabled; callers must use native translator. */\nstatic u32* snx_rb_try(const u8* code, u32 code_len, int stage, const ShaderInfo* state, ShaderInfo* si,\n                       size_t* nw) {\n    if (stage != ST_FS || state->tex_int_mask || state->tex_sint_mask ||\n        state->rt_int_mask || state->rt_sint_mask || state->tex_dc_color_mask ||\n        state->tex_dc_color_funcs || state->in_unfed_mask || state->early_fragment_tests)\n        return NULL;\n    snx_rb_load();\n    for (u32 j = 0; j < snx_rb_count; j++) {\n        const SnxRbEntry* e = &snx_rb_entries[j];\n        if (code_len != e->code_len || memcmp(code, e->code, code_len)) continue;\n        u32* spv = malloc(e->spv_len);\n        if (!spv) return NULL;\n        memcpy(spv, e->spirv, e->spv_len);\n        memcpy(si->sph, code, 80);\n        si->cbuf_mask = e->cbuf_mask;\n        si->in_mask = e->in_mask;\n        si->out_mask = e->out_mask;\n        si->ntex = (int)e->ntex;\n        for (u32 i = 0; i < e->ntex; i++) {\n            si->tex[i] = (ShTex){ .type = 1, .bindless = 1, .bl_cbuf = 2,\n                                  .bl2 = 1, .bl2_cbuf = 2,\n                                  .cbuf_off = e->off0[i], .bl2_off = e->off1[i] };\n        }\n        *nw = e->spv_len / sizeof(u32);\n        WARN(\"vulkan: Ryujinx exact Maxwell match %.16s, %u fragment textures (%u bytes)\\n\",\n             e->key, e->ntex, e->code_len);\n        return spv;\n    }\n    return NULL;\n}\n#endif\n"

INCLUDE_OLD = '#include "nx/gpu/vk/internal_spv.h"'
INCLUDE_NEW = INCLUDE_OLD + '\n#include "nx/gpu/vk/snx_castlevania_ryujinx_bridge.h"'
CALL_OLD = '''        size_t nw = 0;
        u32* spv = vk_translate_spirv(code, 0x10000, stage, &s->si, &nw, sh_cb_read, &s->cbr);'''
CALL_NEW = '''        size_t nw = 0;
        const ShaderInfo native_state = s->si;
        int used_ryujinx_bridge = 0;
        u32* spv = snx_rb_try(code, mlen, stage, &native_state, &s->si, &nw);
        if (spv) {
            const char* reason = vk_spirv_unavailable(spv, nw);
            if (reason) {
                WARN("vulkan: Ryujinx shader not supported by this GPU: %s; using native path\\n", reason);
                free(spv);
                spv = NULL;
                s->si = native_state;
            } else
                used_ryujinx_bridge = 1;
        }
        if (!spv)
            spv = vk_translate_spirv(code, 0x10000, stage, &s->si, &nw, sh_cb_read, &s->cbr);'''
MODULE_OLD = '''            if (!VK_OK(vkCreateShaderModule(g_vk.dev, &mi, NULL, &s->mod)))
                s->failed = 1;
            else
                pf_shader_record(s, spv, nw);
            free(spv);'''
MODULE_NEW = '''            if (!VK_OK(vkCreateShaderModule(g_vk.dev, &mi, NULL, &s->mod))) {
                if (used_ryujinx_bridge) {
                    WARN("vulkan: Ryujinx vkCreateShaderModule failed; retrying native translator\\n");
                    s->si = native_state;
                    size_t fallback_nw = 0;
                    u32* native = vk_translate_spirv(code, 0x10000, stage, &s->si,
                                                      &fallback_nw, sh_cb_read, &s->cbr);
                    if (native) {
                        VkShaderModuleCreateInfo fallback_mi = {
                            .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
                            .codeSize = fallback_nw * 4, .pCode = native };
                        if (VK_OK(vkCreateShaderModule(g_vk.dev, &fallback_mi, NULL, &s->mod)))
                            pf_shader_record(s, native, fallback_nw);
                        else
                            s->failed = 1;
                        free(native);
                    } else
                        s->failed = 1;
                } else
                    s->failed = 1;
            } else if (!used_ryujinx_bridge)
                pf_shader_record(s, spv, nw);
            /* Do not put experimental Ryujinx modules in the shared persistent shader cache. */
            free(spv);'''


def transform(source, revert=False):
    originals = (INCLUDE_OLD, CALL_OLD, MODULE_OLD)
    modified = (INCLUDE_NEW, CALL_NEW, MODULE_NEW)
    if revert:
        if all(source.count(p) == 1 for p in originals) and INCLUDE_NEW not in source:
            return source  # idempotent: already restored
        if not all(source.count(p) == 1 for p in modified):
            raise ValueError("unexpected pinned ScarletNX code or mixed Ryujinx patch")
        for old, new in zip(modified, originals):
            source = source.replace(old, new, 1)
    else:
        if all(source.count(p) == 1 for p in modified):
            return source  # idempotent: already patched
        if INCLUDE_NEW in source or not all(source.count(p) == 1 for p in originals):
            raise ValueError("unexpected pinned ScarletNX code or mixed Ryujinx patch")
        for old, new in zip(originals, modified):
            source = source.replace(old, new, 1)
    return source

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    target = args.source / "src/nx/gpu/vk/pipeline.c"
    header = args.source / "src/nx/gpu/vk/snx_castlevania_ryujinx_bridge.h"
    original = target.read_text()
    result = transform(original, args.revert)
    # Preflight the generated header before changing pipeline.c.
    if header.exists() and header.read_text() != HEADER:
        raise ValueError("generated header differs; refusing to modify source")
    if result != original:
        target.write_text(result)
    if args.revert:
        if header.is_file():
            header.unlink()
    else:
        header.write_text(HEADER)
    print(("Reverted" if args.revert else "Enabled") + " optional Ryujinx Vulkan bridge")


if __name__ == "__main__":
    main()
