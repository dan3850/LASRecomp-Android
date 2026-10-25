/* SPDX-License-Identifier: MIT
 * nxnative/Ryujinx raw compute reflection -> ScarletNX's Vulkan ABI.
 * No title keys, shader allowlists or game bytes. The original renderer owns
 * allocation, dispatch, barriers, alias checks and guest-visible writeback.
 */
#include "nx/runtime/driver/hactool/cJSON.h"

typedef struct { u32 binding, target, cls; } SnxNxBinding;
typedef struct { u32 binding, set, pointer, storage, pointee, block; } SnxNxId;

static int snx_nx_number(const cJSON* o, const char* key, u32 max, u32* out) {
    const cJSON* v = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!cJSON_IsNumber(v) || v->valuedouble < 0 || v->valuedouble > max ||
        v->valuedouble != (double)(u32)v->valuedouble) return 0;
    *out = (u32)v->valuedouble;
    return 1;
}
static int snx_nx_empty_array(const cJSON* o, const char* key) {
    const cJSON* a = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsArray(a) && !a->child;
}
static int snx_nx_binding(SnxNxBinding* b, u32* count, u32 old, u32 target, u32 cls) {
    if (!old || old > 4096 || *count >= 24) return 0;
    for (u32 i = 0; i < *count; i++)
        if (b[i].binding == old || b[i].target == target) return 0;
    b[(*count)++] = (SnxNxBinding){old, target, cls};
    return 1;
}

/* Only buffer compute is accepted here. Unsupported resources retain the
 * existing native path; accepting guessed texture/image facts would be wrong.
 * The managed facade gives exactly this reflection, as does nxnative's CLI.
 */
static int snx_nx_reflect(const char* json, ShaderInfo* si, SnxNxBinding b[24], u32* count) {
    cJSON* root = cJSON_ParseWithOpts(json, NULL, 1);
    const cJSON* stage = cJSON_GetObjectItemCaseSensitive(root, "stage");
    const cJSON* cb = cJSON_GetObjectItemCaseSensitive(root, "cbufs");
    const cJSON* sb = cJSON_GetObjectItemCaseSensitive(root, "sbufs");
    u32 mask = 0, writes = 0, offsets[16] = {0}, nbuf = 0;
    int ok = cJSON_IsObject(root) && cJSON_IsString(stage) && !strcmp(stage->valuestring, "cs") &&
             cJSON_IsArray(cb) && cJSON_IsArray(sb) && snx_nx_empty_array(root, "textures") &&
             snx_nx_empty_array(root, "images") && snx_nx_empty_array(root, "notes");
    *count = 0;
    for (const cJSON* p = ok ? cb->child : NULL; p && ok; p = p->next) {
        u32 binding, slot;
        ok = cJSON_IsObject(p) && snx_nx_number(p, "binding", 4096, &binding) &&
             snx_nx_number(p, "slot", 7, &slot) && !(mask & (1u << slot)) &&
             snx_nx_binding(b, count, binding, SNX_VKB_CB + slot, 2);
        if (ok) mask |= 1u << slot;
    }
    for (const cJSON* p = ok ? sb->child : NULL; p && ok; p = p->next) {
        u32 binding, slot, cbslot, off, flags;
        ok = nbuf < 16 && cJSON_IsObject(p) && snx_nx_number(p, "binding", 4096, &binding) &&
             snx_nx_number(p, "slot", 15, &slot) && snx_nx_number(p, "cb_slot", 0, &cbslot) &&
             snx_nx_number(p, "cb_offset", 16381, &off) && snx_nx_number(p, "flags", 1, &flags) &&
             snx_nx_binding(b, count, binding, SNX_VKB_SSBO + nbuf, 3);
        /* Ryujinx offsets are WORDS. ScarletNX's descriptor offsets are BYTES. */
        if (ok) {
            for (u32 i = 0; i < nbuf; i++) if (offsets[i] == off * 4) ok = 0;
            offsets[nbuf] = off * 4;
            if (flags) writes |= 1u << nbuf;
            nbuf++;
        }
    }
    if (ok) {
        si->stage = ST_CS;
        si->cbuf_mask = mask;
        memset(si->cbuf_max, 0, sizeof si->cbuf_max);
        si->ngbuf = (int)nbuf;
        memcpy(si->gbuf_cbuf_off, offsets, sizeof offsets);
        si->gbuf_wmask = writes;
        si->ntex = si->nimg = si->unsupported = 0;
        si->first_unsupported[0] = 0;
    }
    cJSON_Delete(root);
    return ok;
}

/* Validate before changing a word. Strip only declarations whose features are
 * proved unused: the raw translator emits optional capabilities universally.
 * In particular an actual FP64 type or a support-buffer read is refused.
 */
static u32* snx_nx_adapt(const u32* src, size_t words, const char* reflection,
                         ShaderInfo* info, size_t* result_words) {
    if (!src || words < 5 || words > 1048576 || src[0] != 0x07230203u ||
        src[1] < 0x00010000u || src[1] > 0x00010300u || src[4] || !src[3] || src[3] > 262144) return NULL;
    ShaderInfo trial = *info;
    SnxNxBinding bindings[24];
    u32 nbind;
    if (!snx_nx_reflect(reflection, &trial, bindings, &nbind)) return NULL;
    SnxNxId* ids = calloc(src[3], sizeof *ids);
    if (!ids) return NULL;
    for (u32 i = 0; i < src[3]; i++) ids[i].binding = ids[i].set = ~0u;
    u32 entry = 0, support = 0, resources = 0;
    int valid = 1, group = 0, local = 0;
    for (size_t at = 5; at < words && valid;) {
        u32 n = src[at] >> 16, op = src[at] & 65535u;
        const u32* a = src + at + 1;
        if (!n || n > words - at) { valid = 0; break; }
        if (op == 15) { /* OpEntryPoint, exact compute/main ABI */
            if (n < 5 || a[0] != 5 || a[1] >= src[3] || a[2] != 0x6e69616du || a[3] || entry) valid = 0;
            else entry = a[1];
        }
        if (op == 16 && n >= 3 && a[1] == 17) { /* LocalSize */
            if (n != 6 || local || a[0] != entry || a[2] != trial.cs_local[0] || a[3] != trial.cs_local[1] ||
                a[4] != trial.cs_local[2]) valid = 0;
            local = 1;
        }
        if (op == 22 && (n != 3 || a[1] != 32)) valid = 0; /* no FP16/64 */
        if (op == 21 && (n != 4 || a[1] != 32)) valid = 0; /* no Int64 */
        if (op == 25 || op == 27 || op == 10) valid = 0; /* images or extensions outside this port */
        if (op >= 333 && op <= 366) group = 1;
        if (op == 71 && n >= 3) {
            if (a[0] >= src[3]) valid = 0;
            else if (a[1] == 33 || a[1] == 34) {
                if (n != 4) valid = 0;
                else {
                    u32* v = a[1] == 33 ? &ids[a[0]].binding : &ids[a[0]].set;
                    if (*v != ~0u) valid = 0;
                    *v = a[2];
                }
            } else if (a[1] == 2 || a[1] == 3) ids[a[0]].block = a[1];
        }
        if (op == 32) { /* pointer -> struct, storage class */
            if (n != 4 || a[0] >= src[3] || a[2] >= src[3]) valid = 0;
            else { ids[a[0]].pointee = a[2]; ids[a[0]].storage = a[1]; }
        }
        if (op == 59) {
            if (n < 4 || a[0] >= src[3] || a[1] >= src[3]) valid = 0;
            else { ids[a[1]].pointer = a[0]; ids[a[1]].storage = a[2]; }
        }
        at += n;
    }
    /* Subgroup instructions need additional device/warp semantics. This
       first buffer-compute slice retains the native implementation for them. */
    if (!entry || !local || group) valid = 0;
    u32 seen = 0;
    for (u32 id = 1; id < src[3] && valid; id++) {
        if (ids[id].binding == ~0u && ids[id].set == ~0u) continue;
        if (ids[id].set || ids[id].binding == ~0u || !ids[id].pointer || ids[id].storage != 2 ||
            ids[ids[id].pointer].storage != 2) { valid = 0; break; }
        u32 block = ids[ids[ids[id].pointer].pointee].block;
        if (!ids[id].binding) {
            if (support || block != 2) valid = 0;
            support = id;
        } else {
            u32 j;
            for (j = 0; j < nbind && bindings[j].binding != ids[id].binding; j++) {}
            if (j == nbind || (seen & (1u << j)) || block != bindings[j].cls) valid = 0;
            else seen |= 1u << j;
            resources++;
        }
    }
    if (resources != nbind || seen != ((1u << nbind) - 1)) valid = 0;
    /* The only support-buffer pointer instructions this translator emits.
       Pointer parameters/aliases would require capabilities rejected below. */
    for (size_t at = 5; at < words && valid;) {
        u32 n = src[at] >> 16, op = src[at] & 65535u;
        const u32* a = src + at + 1;
        if (support && (((op == 61 || op == 65 || op == 66 || op == 67 || op == 70 || op == 83) &&
                         n >= 4 && a[2] == support) ||
                        ((op == 62 || op == 63 || op == 64) && n >= 2 && a[0] == support))) valid = 0;
        if (op == 57 && support) for (u32 j = 3; j + 1 < n; j++) if (a[j] == support) valid = 0;
        if (op == 17 && (n != 2 || (a[0] != 1 && a[0] != 10 && a[0] != 25 && a[0] != 46 &&
            a[0] != 47 && a[0] != 50 && a[0] != 62 && a[0] != 64 && a[0] != 65))) valid = 0;
        at += n;
    }
    u32* dst = valid ? malloc(words * 4) : NULL;
    if (dst) {
        size_t out = 5;
        memcpy(dst, src, 20);
        for (size_t at = 5; at < words;) {
            u32 n = src[at] >> 16, op = src[at] & 65535u;
            const u32* a = src + at + 1;
            int remove = (op == 17 && a[0] != 1 && !(group && (a[0] == 62 || a[0] == 64 || a[0] == 65))) ||
                         (support && ((op == 5 && n >= 2 && a[0] == support) ||
                           (op == 71 && n >= 3 && a[0] == support) ||
                           (op == 59 && n >= 4 && a[1] == support)));
            if (!remove) {
                memcpy(dst + out, src + at, n * 4);
                if (op == 71 && n == 4 && (a[1] == 33 || a[1] == 34)) {
                    if (a[1] == 34) dst[out + 3] = 0; /* compute set */
                    else for (u32 j = 0; j < nbind; j++)
                        if (bindings[j].binding == a[2]) dst[out + 3] = bindings[j].target;
                }
                out += n;
            }
            at += n;
        }
        *result_words = out;
        *info = trial;
    }
    free(ids);
    return dst;
}
