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
 * Ryujinx NativeAOT on-device translator: live Vulkan-path diagnostic only.
 * No shader pack, no private Maxwell data, no mutation of GPU shader state.
 * A follow-up iteration will bind SPIR-V only with truthful descriptors.
 */
#ifndef SNX_RYUJINX_NATIVE_LIVE_PROBE_H
#define SNX_RYUJINX_NATIVE_LIVE_PROBE_H
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    uint8_t *spirv;
    size_t spirv_bytes;
    uint8_t *reflection_json;
    size_t reflection_bytes;
    uint8_t *error;
    size_t error_bytes;
} SnxRnResult;

typedef int (*SnxRnVersion)(void);
typedef int (*SnxRnTranslate)(const uint8_t*, size_t, const uint8_t*, size_t, SnxRnResult*);
typedef void (*SnxRnFree)(SnxRnResult*);

static void *snx_rn_lib;
static SnxRnVersion snx_rn_version;
static SnxRnTranslate snx_rn_translate;
static SnxRnFree snx_rn_free;
static unsigned snx_rn_attempts;
static int snx_rn_started;

/* Return 0 unless all three symbols exist and the library ABI is v1. */
static int snx_rn_init(void) {
    if (snx_rn_started) return snx_rn_translate != NULL;
    snx_rn_started = 1;
    const char *enabled = getenv("SNX_RYUJINX_NATIVE_PROBE");
    if (!enabled || strcmp(enabled, "1")) return 0;
    snx_rn_lib = dlopen("libRyujinxShaderNative.so", RTLD_NOW | RTLD_LOCAL);
    if (!snx_rn_lib) {
        WARN("vulkan: RYUJINX_NATIVE_PROBE: dlopen failed: %s\n", dlerror());
        return 0;
    }
    snx_rn_version = (SnxRnVersion)dlsym(snx_rn_lib, "snx_ryu_api_version");
    snx_rn_translate = (SnxRnTranslate)dlsym(snx_rn_lib, "snx_ryu_translate_v1");
    snx_rn_free = (SnxRnFree)dlsym(snx_rn_lib, "snx_ryu_free_v1");
    if (!snx_rn_version || !snx_rn_translate || !snx_rn_free || snx_rn_version() != 1) {
        WARN("vulkan: RYUJINX_NATIVE_PROBE: unsupported NativeAOT ABI, using ScarletNX\n");
        snx_rn_translate = NULL;
        dlclose(snx_rn_lib);
        snx_rn_lib = NULL;
        return 0;
    }
    WARN("vulkan: RYUJINX_NATIVE_PROBE: real C# translator loaded in game process (ABI 1)\n");
    return 1;
}

/* Only failed fragment programs, up to 32 translations, to bound overhead.
 * The JSON supplies defaults solely for a diagnostic translation. It is
 * not a real resource map and MUST NEVER be used for actual drawing.
 */
static void snx_rn_live_probe(const uint8_t *code, uint32_t code_len, int stage) {
    if (stage != ST_FS || !code || code_len < 88 || code_len > 65536 ||
        (code_len & 7) || snx_rn_attempts >= 32) return;
    if (!snx_rn_init()) return;
    static const char job[] =
        "{\"stage\":\"ps\",\"tex\":{},\"img\":{},\"attr\":{},\"fout\":{},"
        "\"local\":[1,1,1],\"debug\":true}";
    snx_rn_attempts++;
    SnxRnResult out = {0};
    const int rc = snx_rn_translate(code, code_len, (const uint8_t *)job,
                                    sizeof(job) - 1, &out);
    if (!rc && out.spirv && out.spirv_bytes >= 20 && out.spirv_bytes <= 4194304 &&
        !(out.spirv_bytes & 3) && ((const uint32_t*)out.spirv)[0] == 0x07230203u &&
        out.reflection_json && out.reflection_bytes > 8) {
        WARN("vulkan: RYUJINX_NATIVE_PROBE: translated NEW fragment Maxwell "
             "(%u bytes -> %zu SPIR-V, %zu reflection), diagnostic only; "
             "original ScarletNX failure retained\n",
             code_len, out.spirv_bytes, out.reflection_bytes);
    } else {
        WARN("vulkan: RYUJINX_NATIVE_PROBE: translate failed (rc=%d, Maxwell=%u, "
             "error=%.*s), original ScarletNX result retained\n",
             rc, code_len, (int)(out.error_bytes < 180 ? out.error_bytes : 180),
             out.error ? (const char*)out.error : "");
    }
    snx_rn_free(&out);
}
#endif
'''

INCLUDE_OLD = '#include "nx/gpu/vk/internal_spv.h"'
INCLUDE_NEW = INCLUDE_OLD + '\n#include "nx/gpu/vk/snx_ryujinx_native_live_probe.h"'
CALL_OLD = '''        if (spv) {
            VkShaderModuleCreateInfo mi = {'''
CALL_NEW = '''        /* Shadow-translate only on native failure; NEVER change SPIR-V
           or the renderer until its descriptor semantics are audited. */
        if (!spv && stage == ST_FS)
            snx_rn_live_probe(code, mlen, stage);
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
