#!/usr/bin/env python3
"""Opt-in LIVE NativeAOT Ryujinx translation probe in pinned ScarletNX Vulkan.

This is the first runtime integration of the REAL C# translator: each failed
fragment shader is translated inside the Android game process, not converted
into an imported shader pack. Results are logged, never bound to Vulkan
until descriptor/IO state adaptation is verified. No fallback is replaced.

Apply only to temporary checked-out pinned ScarletNX; --revert restores it.
"""
import argparse
from pathlib import Path

HEADER = r'''/* SPDX-License-Identifier: MIT
 * Automatic Ryujinx NativeAOT -> ScarletNX Vulkan fragment shader fallback.
 * Converts arbitrary source Maxwell fragments into descriptor-compatible
 * SPIR-V through the REAL on-device Ryujinx translator. Fail-closed.
 * No shader pack, no game-specific allowlist or pre-translated assets.
 */
#ifndef SNX_RYUJINX_NATIVE_LIVE_PROBE_H
#define SNX_RYUJINX_NATIVE_LIVE_PROBE_H
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* Version 1 of the C ABI also used by standalone Termux tests. */
typedef struct {
    uint8_t *spirv;
    size_t spirv_bytes;
    uint8_t *reflection_json;
    size_t reflection_bytes;
    uint8_t *error;
    size_t error_bytes;
} SnxRnResult;
typedef struct {
    uint32_t version, stage, cbuf_mask, input_mask, output_mask, texture_count;
    uint32_t texture_info[64 * 4];
} SnxRnScarletMeta;
typedef int (*SnxRnVersion)(void);
typedef int (*SnxRnAdapt)(const uint8_t*, size_t, const uint8_t*, size_t,
                          SnxRnResult*, SnxRnScarletMeta*);
typedef void (*SnxRnFree)(SnxRnResult*);

static void *snx_rn_lib;
static SnxRnVersion snx_rn_version;
static SnxRnAdapt snx_rn_adapt;
static SnxRnFree snx_rn_free;
static unsigned snx_rn_attempts;
static int snx_rn_started;

static int snx_rn_init(void) {
    if (snx_rn_started) return snx_rn_adapt != NULL;
    snx_rn_started = 1;
    const char *enabled = getenv("SNX_RYUJINX_NATIVE_PROBE");
    if (!enabled || strcmp(enabled, "1")) return 0;
    snx_rn_lib = dlopen("libRyujinxShaderNative.so", RTLD_NOW | RTLD_LOCAL);
    if (!snx_rn_lib) {
        WARN("vulkan: RYUJINX_NATIVE_VULKAN: dlopen failed: %s\n", dlerror());
        return 0;
    }
    snx_rn_version = (SnxRnVersion)dlsym(snx_rn_lib, "snx_ryu_api_version");
    snx_rn_adapt = (SnxRnAdapt)dlsym(snx_rn_lib, "snx_ryu_translate_scarlet_v1");
    snx_rn_free = (SnxRnFree)dlsym(snx_rn_lib, "snx_ryu_free_v1");
    if (!snx_rn_version || !snx_rn_adapt || !snx_rn_free || snx_rn_version() != 1) {
        WARN("vulkan: RYUJINX_NATIVE_VULKAN: new descriptor adapter ABI missing; ScarletNX unchanged\n");
        snx_rn_adapt = NULL;
        dlclose(snx_rn_lib);
        snx_rn_lib = NULL;
        return 0;
    }
    WARN("vulkan: RYUJINX_NATIVE_VULKAN: real Ryujinx NativeAOT dynamic adapter ready, "
         "binding only validated SPIR-V (ABI 1)\n");
    return 1;
}

/* Called only after ScarletNX itself failed. A new shader is tried once per
 * shader-cache entry. No fallback state is touched before all checks pass.
 */
static u32* snx_rn_live_try_vulkan(const uint8_t *code, uint32_t code_len,
                                    int stage, ShaderInfo* si, size_t* words) {
    if (stage != ST_FS || !code || code_len < 88 || code_len > 65536 ||
        (code_len & 7) || snx_rn_attempts >= 256) return NULL;
    if (!snx_rn_init()) return NULL;
    const ShaderInfo original = *si;
    /* Ryujinx does not yet model runtime integer-output or unfed-varying
     * semantics on this bridge. Retain ScarletNX failure for those states.
     */
    if (original.tex_int_mask || original.tex_sint_mask || original.rt_int_mask ||
        original.rt_sint_mask || original.tex_dc_color_mask || original.tex_dc_color_funcs ||
        original.in_unfed_mask || original.early_fragment_tests) {
        WARN("vulkan: RYUJINX_NATIVE_VULKAN: unsupported special fragment state; native fallback\n");
        return NULL;
    }
    static const char job[] =
        "{\"stage\":\"ps\",\"tex\":{},\"img\":{},\"attr\":{},\"fout\":{},"
        "\"local\":[1,1,1],\"debug\":true}";
    snx_rn_attempts++;
    SnxRnResult out = {0};
    SnxRnScarletMeta meta = {0};
    const int rc = snx_rn_adapt(code, code_len, (const uint8_t *)job,
                                sizeof(job) - 1, &out, &meta);
    u32* adapted = NULL;
    int valid = rc == 0 && meta.version == 1 && meta.stage == 4 &&
                meta.texture_count <= SH_MAXTEX && meta.output_mask &&
                !(meta.cbuf_mask & ~((1u << 18) - 1u)) &&
                out.spirv && out.spirv_bytes >= 20 &&
                out.spirv_bytes <= 4194304 && !(out.spirv_bytes & 3) &&
                ((const u32*)out.spirv)[0] == 0x07230203u;
    if (valid) {
        ShaderInfo trial = original;
        trial.stage = stage;
        trial.unsupported = 0;
        trial.first_unsupported[0] = 0;
        memcpy(trial.sph, code, 80);
        trial.cbuf_mask = meta.cbuf_mask;
        memset(trial.cbuf_max, 0, sizeof trial.cbuf_max);
        trial.in_mask = meta.input_mask;
        trial.out_mask = meta.output_mask;
        trial.ntex = (int)meta.texture_count;
        trial.nimg = 0;
        trial.ngbuf = 0;
        for (uint32_t i = 0; i < meta.texture_count; i++) {
            uint32_t j = 4 * i;
            uint32_t cb0 = meta.texture_info[j], off0 = meta.texture_info[j + 1];
            uint32_t cb1 = meta.texture_info[j + 2], off1 = meta.texture_info[j + 3];
            if (cb0 >= 18 || cb1 >= 18 || off0 >= 16384 || off1 >= 16384) {
                valid = 0;
                break;
            }
            trial.tex[i] = (ShTex){.type = 1, .bindless = 1,
                                  .bl_cbuf = (u8)cb0, .cbuf_off = off0,
                                  .bl2 = 1, .bl2_cbuf = (u8)cb1, .bl2_off = off1};
        }
        if (valid) {
            adapted = malloc(out.spirv_bytes);
            if (adapted) {
                memcpy(adapted, out.spirv, out.spirv_bytes);
                *words = out.spirv_bytes / 4;
                *si = trial;
                WARN("vulkan: RYUJINX_NATIVE_VULKAN: shader adapted automatically: "
                     "%u Maxwell bytes -> %zu SPIR-V bytes, %u textures, "
                     "CB mask %05x, IO %08x/%02x\n",
                     code_len, out.spirv_bytes, meta.texture_count,
                     meta.cbuf_mask, meta.input_mask, meta.output_mask);
            }
        }
    }
    if (!adapted) {
        WARN("vulkan: RYUJINX_NATIVE_VULKAN: fallback after adapter rc=%d, "
             "Maxwell=%u, error=%.*s\n", rc, code_len,
             (int)(out.error_bytes < 160 ? out.error_bytes : 160),
             out.error ? (const char*)out.error : "");
    }
    snx_rn_free(&out);
    return adapted;
}
#endif
'''

INCLUDE_OLD = '#include "nx/gpu/vk/internal_spv.h"'
INCLUDE_NEW = INCLUDE_OLD + '\n#include "nx/gpu/vk/snx_ryujinx_native_live_probe.h"'
CALL_OLD = '''        if (spv) {
            VkShaderModuleCreateInfo mi = {'''
CALL_NEW = '''        /* Real, opt-in Ryujinx-to-ScarletNX Vulkan fallback. Only a validated
           descriptor/IO adapter may replace a shader ScarletNX already rejected. */
        if (!spv && stage == ST_FS) {
            ShaderInfo candidate = s->si;
            size_t cnw = 0;
            u32* adapted = snx_rn_live_try_vulkan(code, mlen, stage, &candidate, &cnw);
            if (adapted) {
                const char* why = vk_spirv_unavailable(adapted, cnw);
                if (!why) {
                    s->si = candidate;
                    nw = cnw;
                    spv = adapted;
                } else {
                    WARN("vulkan: RYUJINX_NATIVE_VULKAN: GPU rejected capability: %s; original fallback\\n", why);
                    free(adapted);
                }
            }
        }
        if (spv) {
            VkShaderModuleCreateInfo mi = {'''


def transform(source: str, revert=False):
    if revert:
        if source.count(INCLUDE_OLD) == 1 and source.count(CALL_OLD) == 1 and INCLUDE_NEW not in source:
            return source
        if source.count(INCLUDE_NEW) != 1 or source.count(CALL_NEW) != 1:
            raise ValueError("live Ryujinx probe patch not found or malformed")
        return source.replace(CALL_NEW, CALL_OLD, 1).replace(INCLUDE_NEW, INCLUDE_OLD, 1)
    if source.count(INCLUDE_NEW) == 1 and source.count(CALL_NEW) == 1:
        return source
    if INCLUDE_NEW in source or source.count(INCLUDE_OLD) != 1 or source.count(CALL_OLD) != 1:
        raise ValueError("pinned ScarletNX Vulkan pipeline changed; refuse patch")
    return source.replace(INCLUDE_OLD, INCLUDE_NEW, 1).replace(CALL_OLD, CALL_NEW, 1)


def apply(root: Path, revert=False):
    pipeline = root / "src/nx/gpu/vk/pipeline.c"
    header = root / "src/nx/gpu/vk/snx_ryujinx_native_live_probe.h"
    original = pipeline.read_text()
    updated = transform(original, revert)
    if header.exists() and header.read_text() != HEADER:
        raise ValueError("generated live probe header differs; refuse to overwrite")
    if updated != original:
        pipeline.write_text(updated)
    if revert:
        header.unlink(missing_ok=True)
    else:
        header.write_text(HEADER)
    print("Ryujinx NativeAOT live Vulkan probe:", "RESTORED" if revert else "INSTALLED")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scarletnx", type=Path)
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    try:
        apply(args.scarletnx, args.revert)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
