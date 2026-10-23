/* SPDX-License-Identifier: MIT
 * ABI 1 only: its ShaderInfo and CB reads are fully represented by PfShader.
 * ABI 2 has extra queried facts and is intentionally unsupported here.
 * Never import or overwrite the native translator's old cache files.
 */
#include <dlfcn.h>
static int snx_ryu_persistent;
static char snx_ryu_suffix[96];

static int snx_ryu_cache_path(char* out, size_t cap, const char* dir, const char* game, const char* extension) {
    int n = snprintf(out, cap, "%s/%s.%s%s", dir, game, snx_ryu_suffix, extension);
    return n >= 0 && (size_t)n < cap;
}

static int snx_ryu_file_hash(const void* fn, u64* hash) {
    Dl_info info;
    PFileMap map = {0};
    if (!dladdr(fn, &info) || !info.dli_fname ||
        plat_file_map(&map, info.dli_fname) || !map.data || !map.size) return 0;
    *hash = vk_hash(map.data, (u64)map.size);
    plat_file_unmap(&map);
    return 1;
}
static int snx_ryu_requested(void) {
    const char* e = getenv("SNX_RYUJINX_NATIVE_PROBE");
    return e && !strcmp(e, "1");
}
static void snx_ryu_cache_setup(size_t dir_len, size_t game_len, size_t path_capacity) {
    const char* e = getenv("SNX_RYU_PERSIST");
    u64 runtime, translator;
    snx_ryu_persistent = 0;
    snx_ryu_suffix[0] = 0;
    if (!snx_ryu_requested()) {
        LOG("SNX_RYU_CACHE_V1 {\"backend\":\"scarlet\",\"persistent\":0}\n");
        return;
    }
    /* Capture needs the original Maxwell input, not cached SPIR-V. */
    if (!e || strcmp(e, "1") || getenv("SNX_SHADER_CORPUS") || g_settings.shader_captures) {
        LOG("SNX_RYU_CACHE_V1 {\"backend\":\"ryujinx_v1\",\"persistent\":0,\"reason\":\"off_or_capture\"}\n");
        return;
    }
    if (!snx_rn_init() || !snx_ryu_file_hash((const void*)snx_rn_adapt, &translator) ||
        !snx_ryu_file_hash((const void*)vk_pipeline_init, &runtime)) {
        WARN("SNX_RYU_CACHE_V1 {\"backend\":\"ryujinx_v1\",\"persistent\":0,\"reason\":\"identity_unavailable\"}\n");
        return;
    }
    u32 device[3] = {g_vk.props.vendorID, g_vk.props.deviceID, g_vk.props.driverVersion};
    u64 driver = vk_hash(g_vk.props.pipelineCacheUUID, 16) ^ vk_hash(device, sizeof device);
    snprintf(snx_ryu_suffix, sizeof snx_ryu_suffix, "ryu1-%016llx-%016llx-%016llx",
             (unsigned long long)runtime, (unsigned long long)translator, (unsigned long long)driver);
    if (dir_len + 1 + game_len + 1 + strlen(snx_ryu_suffix) + strlen(".vkpipelines") + 1 > path_capacity) {
        WARN("SNX_RYU_CACHE_V1 {\"backend\":\"ryujinx_v1\",\"persistent\":0,\"reason\":\"path_too_long\"}\n");
        snx_ryu_suffix[0] = 0;
        return;
    }
    snx_ryu_persistent = 1;
    LOG("SNX_RYU_CACHE_V1 {\"backend\":\"ryujinx_v1\",\"persistent\":1,\"namespace\":\"%s\"}\n",
        snx_ryu_suffix);
}
