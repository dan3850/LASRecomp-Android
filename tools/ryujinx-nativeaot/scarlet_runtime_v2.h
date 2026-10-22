/* SPDX-License-Identifier: MIT
 * Live ABI 2; included after sh_cb_read in the pinned Vulkan pipeline.
 * GPU callbacks run synchronously on the GPU thread. No guest pointers cross
 * into managed code. Every queried fact is retained in the shader cache key.
 */
#include <dlfcn.h>
#include "nx/gpu/vk/snx_ryu_expected.h"
typedef struct { unsigned char *spirv; size_t spirv_bytes; unsigned char *reflection;
    size_t reflection_bytes; unsigned char *error; size_t error_bytes; } SnxRnResultV2;
typedef struct { u32 version, stage, cbuf_mask, input_mask, output_mask, ntex;
    u32 tex[64 * 8]; } SnxRnMetaV2;
typedef struct { int kind, handle, slot, ok; u32 value; } SnxRnFact;
typedef struct { unsigned n; int failed; SnxRnFact f[4096]; } SnxRnFacts;
typedef int (*SnxRnQueryV2)(int, int, int, u32*);
typedef int (*SnxRnTranslateV2)(const u8*, size_t, const u8*, size_t,
                               SnxRnResultV2*, SnxRnMetaV2*, SnxRnQueryV2);
static SnxRnFacts* snx_rn_recording;
static SnxRnTranslateV2 snx_rn_translate;
static void (*snx_rn_release)(SnxRnResultV2*);
static int snx_rn_enabled(void) {
    const char* v = getenv("SNX_RYUJINX_NATIVE_PROBE");
    return v && !strcmp(v, "1");
}
static int snx_rn_init_v2(void) {
    static int started;
    if (!snx_rn_enabled()) return 0;
    if (started) return snx_rn_translate != NULL;
    started = 1;
    void* lib = dlopen("libRyujinxShaderNative.so", RTLD_NOW | RTLD_LOCAL);
    const char* (*identity)(void) = lib ? (const char*(*)(void))dlsym(lib, "snx_ryu_build_identity") : NULL;
    snx_rn_translate = lib ? (SnxRnTranslateV2)dlsym(lib, "snx_ryu_translate_scarlet_v2") : NULL;
    snx_rn_release = lib ? (void(*)(SnxRnResultV2*))dlsym(lib, "snx_ryu_free_v1") : NULL;
    if (!identity || !snx_rn_translate || !snx_rn_release || strcmp(identity(), SNX_RYU_EXPECTED_IDENTITY)) {
        snx_rn_translate = NULL;
        fatal("RYUJINX_NATIVE_V2: stale/missing NativeAOT library; expected %s", SNX_RYU_EXPECTED_IDENTITY);
    }
    LOG("vulkan: RYUJINX_NATIVE_V2: %s; runtime %s; full support UBO and live TIC/CB1 queries\n",
        identity(), SNX_RUNTIME_REVISION);
    return 1;
}
static int snx_rn_query_value(int kind, int handle, int slot, u32* value) {
    *value = 0;
    if (!g_sh_ch) return 0;
    if (kind == 0) return handle >= 0 && !(handle & 3) && sh_cb_read(1, (u32)handle, value);
    if (kind == 4) { *value = g_sh_ch->r3d[0x4C4]; return 1; }
    if (kind == 3) { /* alpha-test function participates in the shader cache key */
        const u32* r = g_sh_ch->r3d;
        u32 fn = r[0x4C5];
        *value = !(r[0x4BB] & 1) ? 8 : fn >= 0x200 && fn <= 0x207 ? fn - 0x200 + 1 : fn >= 1 && fn <= 8 ? fn : 8;
        return 1;
    }
    if (kind != 1 && kind != 2) return 0;
    u32 h = (u32)handle, mode = h >> 28;
    u32 cb0 = slot < 0 ? g_sh_ch->r3d[0x982] : (u32)slot & 65535;
    u32 hi = (u32)slot >> 16, cb1 = slot < 0 || hi == 0 ? cb0 : hi - 1;
    u32 packed = 0, sampler = 0;
    if (mode > 3 || !sh_cb_read(cb0, (h & 0x3fff) * 4, &packed)) return 0;
    if (mode) {
        u32 off = (h >> 14) & 0x3fff;
        if (mode == 3) sampler = off;
        else if (!sh_cb_read(cb1, off * 4, &sampler)) return 0;
        packed |= mode >= 2 ? sampler << 20 : sampler;
    }
    const u32* r = g_sh_ch->r3d;
    u64 pool = ((u64)r[0x55D] << 32) | r[0x55E];
    if (!pool || (packed & 0xfffff) > r[0x55F]) return 0;
    u32 tic[8];
    gmem_read(pool + (packed & 0xfffff) * 32ull, tic, sizeof tic);
    if (kind == 2) { *value = tic[5] >> 31; return 1; }
    /* Ryujinx SamplerType; TIC target enums are Maxwell's, not Vulkan's. */
    static const u32 types[9] = {1, 3, 4, 5, 1 | 256, 3 | 256, 2, 0, 5 | 256};
    u32 target = (tic[4] >> 23) & 15;
    if (target >= 9 || !types[target]) return 0;
    *value = types[target] | (((tic[7] >> 8) & 15) ? 512 : 0);
    return 1;
}
static int snx_rn_query_v2(int kind, int handle, int slot, u32* value) {
    int ok = snx_rn_query_value(kind, handle, slot, value);
    SnxRnFacts* f = snx_rn_recording;
    if (f) {
        unsigned i;
        for (i = 0; i < f->n; i++)
            if (f->f[i].kind == kind && f->f[i].handle == handle && f->f[i].slot == slot) break;
        if (i == f->n) {
            if (i == 4096) { f->failed = 1; return 0; }
            f->f[f->n++] = (SnxRnFact){kind, handle, slot, ok, ok ? *value : 0};
        }
    }
    return ok;
}
static int snx_rn_facts_hold(const VkSh* shader) {
    const SnxRnFacts* f = shader->ryu_facts;
    if (!f) return 1;
    for (unsigned i = 0; i < f->n; i++) {
        const SnxRnFact* x = &f->f[i];
        u32 v = 0;
        int ok = snx_rn_query_value(x->kind, x->handle, x->slot, &v);
        if (ok != x->ok || (ok && v != x->value)) return 0;
    }
    return 1;
}
static u32* snx_rn_try_v2(const u8* code, u32 len, int stage, VkSh* shader, size_t* words) {
    if (stage != ST_FS || !snx_rn_init_v2()) return NULL;
    const ShaderInfo original = shader->si;
    if (original.tex_int_mask || original.rt_int_mask || original.tex_dc_color_mask ||
        original.in_unfed_mask || original.early_fragment_tests) {
        WARN_LIMIT(24, "vulkan: RYUJINX_NATIVE_V2: native translator for integer/unfed/early-Z fragment state\n");
        return NULL;
    }
    char job[160];
    snprintf(job, sizeof job, "{\"stage\":\"ps\",\"debug\":true,\"texture_buffer_index\":%u}", g_sh_ch->r3d[0x982]);
    SnxRnResultV2 out = {0}; SnxRnMetaV2 meta = {0};
    SnxRnFacts* facts = calloc(1, sizeof *facts);
    if (!facts) return NULL;
    snx_rn_recording = facts;
    int rc = snx_rn_translate(code, len, (const u8*)job, strlen(job), &out, &meta, snx_rn_query_v2);
    snx_rn_recording = NULL;
    /* Even a fallback may depend on a previously unavailable descriptor. */
    shader->ryu_facts = facts;
    int valid = !rc && !facts->failed && meta.version == 2 && meta.stage == ST_FS && meta.ntex <= SH_MAXTEX &&
        !(meta.cbuf_mask & ~0x3ffffu) && out.spirv && out.spirv_bytes >= 20 && out.spirv_bytes <= 4194304 &&
        !(out.spirv_bytes & 3) && ((u32*)out.spirv)[0] == 0x07230203;
    ShaderInfo trial = original;
    if (valid) {
        trial.stage = ST_FS; trial.unsupported = 0; trial.first_unsupported[0] = 0;
        memcpy(trial.sph, code, 80);
        trial.cbuf_mask = meta.cbuf_mask; memset(trial.cbuf_max, 0, sizeof trial.cbuf_max);
        trial.in_mask = meta.input_mask; trial.out_mask = 0;
        trial.ntex = (int)meta.ntex; trial.nimg = trial.ngbuf = 0;
        for (u32 i = 0; i < meta.ntex; i++) {
            const u32* t = &meta.tex[8 * i];
            if (t[0] >= 18 || t[2] >= 18 || t[1] >= 16384 || t[3] >= 16384 || t[4] > 3 ||
                t[5] < 1 || t[5] > 3 || t[6] > 1 || t[7] > 1) { valid = 0; break; }
            trial.tex[i] = (ShTex){.cbuf_off = t[1], .type = t[5], .array = t[6], .shadow = t[7],
                .bindless = 1, .bl_cbuf = t[0], .bl2_cbuf = t[2], .bl2_off = t[3], .bl2 = t[4]};
        }
    }
    const char* why = valid ? vk_spirv_unavailable((u32*)out.spirv, out.spirv_bytes / 4) : NULL;
    u32* result = valid && !why ? malloc(out.spirv_bytes) : NULL;
    if (result) {
        memcpy(result, out.spirv, out.spirv_bytes); *words = out.spirv_bytes / 4;
        shader->si = trial; shader->ryujinx = 1;
        LOG("vulkan: RYUJINX_NATIVE_V2: %016llx: %u Maxwell -> %zu SPIR-V bytes, %u textures, %u GPU facts\n",
            (unsigned long long)shader->hash, len, out.spirv_bytes, meta.ntex, facts->n);
    } else {
        WARN("vulkan: RYUJINX_NATIVE_V2: fallback %016llx: rc=%d %s %.*s\n",
             (unsigned long long)shader->hash, rc, why ? why : "", (int)(out.error_bytes < 200 ? out.error_bytes : 200),
             out.error ? (char*)out.error : "");
    }
    snx_rn_release(&out);
    return result;
}
