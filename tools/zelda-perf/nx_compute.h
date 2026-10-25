/* SPDX-License-Identifier: MIT
 * Adapt nxnative's translated-library/chain-stamp cache to Vulkan compute.
 * The existing general NativeAOT library supplies the actual Ryujinx compiler;
 * its raw ABI already supports compute. No Metal code or game data is bundled.
 */
#include <dirent.h>
#include <errno.h>
#include <unistd.h>
#include "nx/gpu/vk/snx_nx_compute_adapter.h"

typedef int (*SnxNxTranslate)(const u8*, size_t, const u8*, size_t, SnxRnResult*);
typedef struct {
    u64 magic, runtime, translator, key, check;
    u32 version, info_bytes, code_bytes, c1_bytes, spirv_words, reserved;
    ShaderInfo info;
} SnxNxCache;
static int snx_nx_ready, snx_nx_started, snx_nx_disk;
static void* snx_nx_lib;
static SnxNxTranslate snx_nx_translate;
static SnxRnFree snx_nx_free;
static char snx_nx_dir[1200];
static u64 snx_nx_runtime, snx_nx_translator, snx_nx_disk_bytes;
static u64 snx_nx_made, snx_nx_loaded, snx_nx_fallback;
#define SNX_NX_CACHE_CAP (64ull << 20)
#define SNX_NX_MAGIC 0x315043584e584e53ull

int snx_nx_compute_enabled(void) {
    const char* s = getenv("SNX_NX_COMPUTE");
    return s && !strcmp(s, "1");
}
void snx_nx_compute_init(void) {
    if (snx_nx_started) return;
    snx_nx_started = 1;
    if (!snx_nx_compute_enabled()) return;
    snx_nx_lib = dlopen("libRyujinxShaderNative.so", RTLD_NOW | RTLD_LOCAL);
    if (snx_nx_lib) {
        SnxRnVersion version = (SnxRnVersion)dlsym(snx_nx_lib, "snx_ryu_api_version");
        snx_nx_translate = (SnxNxTranslate)dlsym(snx_nx_lib, "snx_ryu_translate_v1");
        snx_nx_free = (SnxRnFree)dlsym(snx_nx_lib, "snx_ryu_free_v1");
        snx_nx_ready = version && version() == 1 && snx_nx_translate && snx_nx_free;
    }
    if (!snx_nx_ready) {
        WARN("SNX_NX_COMPUTE_META_V1 enabled=1 ready=0 cache=0; native compute retained\n");
        return;
    }
    const char* persist = getenv("SNX_NX_COMPUTE_CACHE");
    if (persist && !strcmp(persist, "1") &&
        snx_ryu_file_hash((const void*)snx_nx_compute_init, &snx_nx_runtime) &&
        snx_ryu_file_hash((const void*)snx_nx_translate, &snx_nx_translator)) {
        char root[1200];
        int n = snprintf(root, sizeof root, "%sshader_cache", g_cachedir);
        if (n > 0 && (size_t)n < sizeof root) {
            plat_mkdir(root);
            n = snprintf(root, sizeof root, "%sshader_cache/nxnative-compute-v1", g_cachedir);
            if (n > 0 && (size_t)n < sizeof root) {
                plat_mkdir(root);
                n = snprintf(snx_nx_dir, sizeof snx_nx_dir, "%s/%016llx-%016llx", root,
                     (unsigned long long)snx_nx_runtime, (unsigned long long)snx_nx_translator);
                if (n > 0 && (size_t)n < sizeof snx_nx_dir) {
                    plat_mkdir(snx_nx_dir);
                    DIR* dir = opendir(snx_nx_dir);
                    if (dir) {
                        struct dirent* e;
                        snx_nx_disk = 1;
                        while ((e = readdir(dir))) {
                            char path[1400]; struct stat st;
                            n = snprintf(path, sizeof path, "%s/%s", snx_nx_dir, e->d_name);
                            if (n > 0 && (size_t)n < sizeof path && !stat(path, &st) &&
                                S_ISREG(st.st_mode) && st.st_size > 0)
                                snx_nx_disk_bytes += (u64)st.st_size;
                        }
                        closedir(dir);
                    }
                }
            }
        }
    }
    LOG("SNX_NX_COMPUTE_META_V1 enabled=1 ready=1 cache=%d buffer_compute=1 original_driver_c0=1\n", snx_nx_disk);
}

/* The driver's opaque pipeline archive is a different object from portable
 * SPIR-V. Give the new backend its own file too, preserving existing caches. */
static void snx_nx_driver_path(char* path, size_t cap) {
    if (!snx_nx_ready) return;
    const char suffix[] = ".nxcompute1";
    if (strlen(path) + sizeof suffix > cap) {
        snx_nx_ready = snx_nx_disk = 0;
        WARN("SNX_NX_COMPUTE_V1 path too long; native compute retained\n");
        return;
    }
    strcat(path, suffix);
}

static u64 snx_nx_key(const u8* code, u32 len, const u8* c1, u32 c1n, const ShaderInfo* si) {
    u32 state[5] = {si->cs_local[0], si->cs_local[1], si->cs_local[2], (u32)si->shared_size, c1n};
    return vk_hash(code, len) ^ vk_hash(c1, c1n) * 0x9e3779b97f4a7c15ull ^
           vk_hash(state, sizeof state) * 0xc2b2ae3d27d4eb4full;
}
static int snx_nx_path(char* path, size_t cap, u64 key) {
    int n = snprintf(path, cap, "%s/%016llx.nxcs", snx_nx_dir, (unsigned long long)key);
    return n > 0 && (size_t)n < cap;
}
static u64 snx_nx_check(const SnxNxCache* h, const u32* spv) {
    SnxNxCache copy = *h;
    copy.check = 0;
    return vk_hash(&copy, sizeof copy) ^ vk_hash(spv, (u64)h->spirv_words * 4);
}
static u32* snx_nx_load(u64 key, const u8* code, u32 len, const u8* c1, u32 c1n,
                        ShaderInfo* si, size_t* words) {
    if (!snx_nx_disk || getenv("SNX_SHADER_CORPUS") || g_settings.shader_captures) return NULL;
    char path[1400];
    if (!snx_nx_path(path, sizeof path, key)) return NULL;
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    SnxNxCache h;
    u8* input = NULL;
    u32* spv = NULL;
    int ok = fread(&h, 1, sizeof h, f) == sizeof h && h.magic == SNX_NX_MAGIC &&
             h.version == 1 && h.info_bytes == sizeof *si && !h.reserved &&
             h.runtime == snx_nx_runtime && h.translator == snx_nx_translator && h.key == key &&
             h.code_bytes == len && h.c1_bytes == c1n && h.spirv_words >= 5 && h.spirv_words <= 1048576 &&
             h.info.stage == ST_CS && !h.info.unsupported && !h.info.ntex && !h.info.nimg &&
             h.info.ngbuf >= 0 && h.info.ngbuf <= 16 && !(h.info.cbuf_mask & ~255u) &&
             !(h.info.gbuf_wmask >> h.info.ngbuf) &&
             !memcmp(h.info.cs_local, si->cs_local, sizeof si->cs_local) && h.info.shared_size == si->shared_size;
    for (int i = 0; ok && i < h.info.ngbuf; i++)
        if ((h.info.gbuf_cbuf_off[i] & 3) || h.info.gbuf_cbuf_off[i] > 65524) ok = 0;
    if (ok) {
        input = malloc((size_t)len + c1n);
        spv = malloc((size_t)h.spirv_words * 4);
        ok = input && spv && fread(input, 1, (size_t)len + c1n, f) == (size_t)len + c1n &&
             !memcmp(input, code, len) && (!c1n || !memcmp(input + len, c1, c1n)) &&
             fread(spv, 4, h.spirv_words, f) == h.spirv_words && fgetc(f) == EOF && !ferror(f) &&
             h.check == snx_nx_check(&h, spv) && spv[0] == 0x07230203u &&
             !vk_spirv_unavailable(spv, h.spirv_words);
    }
    fclose(f); free(input);
    if (!ok) { free(spv); return NULL; }
    *si = h.info; *words = h.spirv_words;
    snx_nx_loaded++;
    LOG_LIMIT(12, "SNX_NX_COMPUTE_CACHE_V1 hit=%016llx\n", (unsigned long long)key);
    return spv;
}
static void snx_nx_store(u64 key, const u8* code, u32 len, const u8* c1, u32 c1n,
                         const ShaderInfo* si, const u32* spv, size_t words) {
    u64 size = sizeof(SnxNxCache) + (u64)len + c1n + words * 4;
    if (!snx_nx_disk || words > 1048576 || snx_nx_disk_bytes > SNX_NX_CACHE_CAP ||
        size > SNX_NX_CACHE_CAP - snx_nx_disk_bytes) return;
    char path[1400], tmp[1440];
    if (!snx_nx_path(path, sizeof path, key)) return;
    int n = snprintf(tmp, sizeof tmp, "%s.%u.tmp", path, (unsigned)getpid());
    if (n < 0 || (size_t)n >= sizeof tmp) return;
    SnxNxCache h = {0};
    h.magic = SNX_NX_MAGIC; h.runtime = snx_nx_runtime; h.translator = snx_nx_translator; h.key = key;
    h.version = 1; h.info_bytes = sizeof *si; h.code_bytes = len; h.c1_bytes = c1n;
    h.spirv_words = (u32)words; h.info = *si; h.check = snx_nx_check(&h, spv);
    FILE* f = fopen(tmp, "wb");
    if (!f) return;
    int ok = fwrite(&h, 1, sizeof h, f) == sizeof h && fwrite(code, 1, len, f) == len &&
             (!c1n || fwrite(c1, 1, c1n, f) == c1n) && fwrite(spv, 4, words, f) == words && !fflush(f);
    if (fclose(f)) ok = 0;
    if (ok && !rename(tmp, path)) snx_nx_disk_bytes += size;
    else remove(tmp); /* only this process's temporary, never the user's caches */
}

u32* snx_nx_compute_spirv(const u8* code, u32 len, ShaderInfo* si, size_t* words,
                          const u8* c1, u32 c1n) {
    if (!snx_nx_compute_enabled()) return NULL;
    snx_nx_compute_init();
    if (!snx_nx_ready || !code || len < 88 || len > 0x10050 || (len & 7) || c1n > 65536 ||
        (c1n && !c1) || si->tex_int_mask || si->tex_sint_mask || si->rt_int_mask) return NULL;
    const u64 key = snx_nx_key(code, len, c1, c1n, si);
    u32* spv = snx_nx_load(key, code, len, c1, c1n, si, words);
    if (spv) return spv;
    size_t cap = 2ull * c1n + 320;
    char* job = malloc(cap);
    if (!job) return NULL;
    int n = snprintf(job, cap, "{\"stage\":\"cs\",\"tex\":{},\"img\":{},\"attr\":{},\"fout\":{},"
         "\"local\":[%u,%u,%u],\"shared\":%u,\"debug\":true,\"c1\":\"",
         si->cs_local[0], si->cs_local[1], si->cs_local[2], (u32)si->shared_size);
    if (n < 0 || (size_t)n + 2ull * c1n + 3 >= cap) { free(job); return NULL; }
    static const char hex[] = "0123456789abcdef";
    for (u32 i = 0; i < c1n; i++) { job[n++] = hex[c1[i] >> 4]; job[n++] = hex[c1[i] & 15]; }
    job[n++] = '"'; job[n++] = '}'; job[n] = 0;
    SnxRnResult result = {0};
    /* ScarletNX prepends a synthetic 80-byte SPH to compute. The nxnative
       translator expects the original compute instructions, without it. */
    int rc = snx_nx_translate(code + 80, len - 80, (const u8*)job, (size_t)n, &result);
    free(job);
    ShaderInfo trial = *si;
    if (!rc && result.spirv && result.spirv_bytes >= 20 && result.spirv_bytes <= 4194304 &&
        !(result.spirv_bytes & 3) && result.reflection_json && result.reflection_bytes > 0 &&
        result.reflection_bytes <= 262144) {
        char* json = malloc(result.reflection_bytes + 1);
        if (json) {
            memcpy(json, result.reflection_json, result.reflection_bytes); json[result.reflection_bytes] = 0;
            spv = snx_nx_adapt((const u32*)result.spirv, result.spirv_bytes / 4, json, &trial, words);
            free(json);
        }
        if (spv && vk_spirv_unavailable(spv, *words)) { free(spv); spv = NULL; }
    }
    snx_nx_free(&result);
    if (spv) {
        *si = trial; snx_nx_made++;
        snx_nx_store(key, code, len, c1, c1n, si, spv, *words);
        LOG_LIMIT(12, "SNX_NX_COMPUTE_V1 translated=%016llx buffers=%d writes=%x c1_bytes=%u\n",
                  (unsigned long long)key, si->ngbuf, si->gbuf_wmask, c1n);
    } else {
        snx_nx_fallback++;
        LOG_LIMIT(12, "SNX_NX_COMPUTE_V1 native_fallback=%016llx rc=%d\n", (unsigned long long)key, rc);
    }
    return spv;
}
void snx_nx_compute_report(u64 window) {
    static u64 made, loaded, fallback;
    if (!snx_nx_compute_enabled()) return;
    LOG("SNX_NX_COMPUTE_STATS_V1 window=%llu translated=%llu cache_hits=%llu fallback=%llu\n",
        (unsigned long long)window, (unsigned long long)(snx_nx_made - made),
        (unsigned long long)(snx_nx_loaded - loaded), (unsigned long long)(snx_nx_fallback - fallback));
    made = snx_nx_made; loaded = snx_nx_loaded; fallback = snx_nx_fallback;
}
