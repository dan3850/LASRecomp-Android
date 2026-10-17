// Android-native GPU residency experiment. This is a shared data path for
// immutable vertex/index data and packed Maxwell GMEM inputs, replacing
// repeated per-submission staging with persistent GPU-accessible versions.
//
// Unlike external-memory import (not available on Adreno), we explicitly
// stage *changed* pages into device-preferred memory. An in-flight version is
// never mutated: a second buffer is allocated or we fall back to legacy code.
// In particular, no frame-number/hash-only shortcut can hide guest writes.
//
// Legacy fallbacks stay available; this module does not accelerate compute
// stores or texture images yet. No binary/game content is embedded here.
#include "../../kernel.h"
#include "resident_gpu.h"
#include "resident_regions.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define RESIDENT_WAYS 4
#define GEOMETRY_SLOTS 1024
#define GMEM_SLOTS 128
#define GEOMETRY_LIMIT (64ull << 20)
#define GMEM_LIMIT (32ull << 20)
#define MAX_COPY_REGIONS 64
#define PAGE_BYTES 4096ull
#define MAX_ID_BYTES 2048

typedef struct {
    uint8_t *identity;
    size_t id_size;
    uint8_t *shadow;
    size_t size, capacity;
    uint64_t key, used_seq;
    VkBuffer buffer;
    VmaAllocation allocation;
} ResidentSlot;

typedef struct {
    ResidentSlot *slots;
    unsigned slot_count;
    uint64_t budget, bytes;
    uint64_t hits, misses, refreshes, allocations, busy, fallback;
    uint64_t uploaded_bytes, reused_bytes, scanned_bytes;
} ResidentPool;

static ResidentSlot geometry_slots[GEOMETRY_SLOTS], gmem_slots[GMEM_SLOTS];
static ResidentPool pools[] = {
    {.slots = geometry_slots, .slot_count = GEOMETRY_SLOTS, .budget = GEOMETRY_LIMIT},
    {.slots = gmem_slots, .slot_count = GMEM_SLOTS, .budget = GMEM_LIMIT}
};
static int enabled = -1;

bool vk_resident_enabled(void) {
    if (enabled < 0) {
        const char *env = getenv("LARECOMP_VK_NATIVE_RESIDENT");
#ifdef __ANDROID__
        enabled = !env || atoi(env) != 0;
#else
        enabled = env && atoi(env) != 0;
#endif
        LOG("[vk-resident] %s: device-preferred immutable geometry + GMEM, "
            "4-way versions, 64+32 MiB budgets; LARECOMP_VK_NATIVE_RESIDENT=%s\n",
            enabled ? "enabled" : "disabled", env ? env : "unset");
    }
    return enabled != 0;
}

static uint64_t hash_key(uint64_t x) {
    x ^= x >> 33; x *= 0xff51afd7ed558ccdull;
    x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ull;
    return x ^ (x >> 33);
}

static void drop_slot(ResidentPool *pool, ResidentSlot *s) {
    if (s->buffer) {
        vmaDestroyBuffer(g_vk.vma, s->buffer, s->allocation);
        pool->bytes -= s->capacity;
    }
    free(s->shadow);
    free(s->identity);
    memset(s, 0, sizeof *s);
}

static bool identity_matches(const ResidentSlot *s, const VkResidentRequest *r) {
    return s->buffer && s->key == r->key && s->id_size == r->identity_size &&
        !memcmp(s->identity, r->identity, r->identity_size);
}

static void failed(ResidentPool *pool) { pool->fallback++; }

// No writable handles are exposed; compute writeback stays in its own
// synchronized path. Stage copies go in the submission's upload CB, which
// executes before its main CB. Old versions survive until timeline completion.
VkSpan vk_resident_get(const VkResidentRequest *r) {
    if (!vk_resident_enabled() || !r || (unsigned)r->domain > VK_RESIDENT_GMEM ||
        !r->identity || !r->identity_size || r->identity_size > MAX_ID_BYTES ||
        !r->context || !r->fill || !r->equal || !r->size ||
        r->size > SIZE_MAX - 3) return (VkSpan){0};

    ResidentPool *pool = &pools[r->domain];
    size_t padded = (r->size + 3) & ~(size_t)3;
    if ((uint64_t)padded > pool->budget || padded > (2ull << 20)) {
        failed(pool);
        return (VkSpan){0};
    }

    unsigned bucket = (unsigned)(hash_key(r->key) %
        (pool->slot_count / RESIDENT_WAYS)) * RESIDENT_WAYS;
    uint64_t pending = vk_pending_seq();
    ResidentSlot *same_done = NULL, *empty = NULL, *lru = NULL;
    // Verify ALL guest bytes first. A cache hit requires no Vulkan driver
    // timeline query; query completion only when we need to replace a version.
    for (unsigned i = bucket; i < bucket + RESIDENT_WAYS; ++i) {
        ResidentSlot *s = &pool->slots[i];
        if (!identity_matches(s, r) || s->size < r->size) continue;
        pool->scanned_bytes += r->size;
        if (r->equal(s->shadow, r->context, r->size)) {
            s->used_seq = pending;
            pool->hits++;
            pool->reused_bytes += r->size;
            return (VkSpan){s->buffer, 0, NULL};
        }
    }
    uint64_t done = vk_completed_seq();
    for (unsigned i = bucket; i < bucket + RESIDENT_WAYS; ++i) {
        ResidentSlot *s = &pool->slots[i];
        if (!s->buffer) { if (!empty) empty = s; continue; }
        if (!resident_rewrite_safe(s->used_seq, done)) continue;
        if (identity_matches(s, r) && s->size == r->size) same_done = s;
        if (!lru || s->used_seq < lru->used_seq) lru = s;
    }

    // Reuse a completed version; never overwrite a currently bound version,
    // including one recorded into an as-yet-unsubmitted main CB.
    ResidentSlot *s = same_done ? same_done : empty ? empty : lru;
    if (!s) { pool->busy++; failed(pool); return (VkSpan){0}; }

    bool can_delta = identity_matches(s, r) && s->size == r->size &&
        resident_rewrite_safe(s->used_seq, done);
    uint8_t *fresh = calloc(1, padded);
    uint8_t *fresh_id = malloc(r->identity_size);
    if (!fresh || !fresh_id) {
        free(fresh); free(fresh_id); failed(pool); return (VkSpan){0};
    }
    memcpy(fresh_id, r->identity, r->identity_size);
    r->fill(fresh, r->context, r->size);

    // Reuse the device buffer allocation only if its old readers finished.
    // Allocate before destroying the old buffer so failure preserves fallback.
    bool need_buffer = !s->buffer || s->capacity < padded;
    VkBuffer new_buffer = VK_NULL_HANDLE;
    VmaAllocation new_allocation = NULL;
    if (need_buffer) {
        uint64_t next_bytes = pool->bytes - (s->buffer ? s->capacity : 0) + padded;
        if (next_bytes > pool->budget) {
            free(fresh); free(fresh_id); failed(pool); return (VkSpan){0};
        }
        VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = padded, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                (r->domain == VK_RESIDENT_GEOMETRY
                    ? (VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT)
                    : VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)};
        VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
        if (vmaCreateBuffer(g_vk.vma, &bi, &ai, &new_buffer, &new_allocation, NULL) != VK_SUCCESS) {
            free(fresh); free(fresh_id); failed(pool); return (VkSpan){0};
        }
    }

    ResidentRegion regions[MAX_COPY_REGIONS];
    size_t nregion = SIZE_MAX;
    if (can_delta && !need_buffer)
        nregion = resident_dirty_regions(s->shadow, fresh, padded,
                                         PAGE_BYTES, regions, MAX_COPY_REGIONS);

    if (nregion == SIZE_MAX) {
        nregion = 1;
        regions[0] = (ResidentRegion){0, padded};
    }
    size_t total_dirty = 0;
    for (size_t i = 0; i < nregion; ++i) total_dirty += regions[i].size;
    if (total_dirty) {
        VkSpan staging = vk_transient(total_dirty, 16);
        VkBufferCopy copies[MAX_COPY_REGIONS];
        size_t packed = 0;
        for (size_t i = 0; i < nregion; ++i) {
            memcpy((uint8_t *)staging.ptr + packed,
                   fresh + regions[i].offset, regions[i].size);
            copies[i] = (VkBufferCopy){staging.off + packed, regions[i].offset,
                                      regions[i].size};
            packed += regions[i].size;
        }
        // No submit/wait here. This copy is ordered before reads in vk_cmd().
        vkCmdCopyBuffer(vk_upload_cmd(), staging.buf,
                        need_buffer ? new_buffer : s->buffer,
                        (uint32_t)nregion, copies);
        pool->uploaded_bytes += total_dirty;
    }

    if (need_buffer) {
        drop_slot(pool, s);
        s->buffer = new_buffer;
        s->allocation = new_allocation;
        s->capacity = padded;
        pool->bytes += padded;
        pool->allocations++;
    } else if (can_delta) {
        pool->refreshes++;
    }
    free(s->shadow);
    free(s->identity);
    s->shadow = fresh;
    s->identity = fresh_id;
    s->id_size = r->identity_size;
    s->size = r->size;
    s->key = r->key;
    s->used_seq = pending;
    pool->misses++;
    return (VkSpan){s->buffer, 0, NULL};
}

void vk_resident_reset(void) {
    for (unsigned p = 0; p < 2; ++p) {
        ResidentPool *pool = &pools[p];
        for (unsigned i = 0; i < pool->slot_count; ++i)
            drop_slot(pool, &pool->slots[i]);
        pool->hits = pool->misses = pool->refreshes = pool->allocations = 0;
        pool->busy = pool->fallback = 0;
        pool->uploaded_bytes = pool->reused_bytes = pool->scanned_bytes = 0;
    }
}

void vk_resident_stats_append(char *buf, size_t capacity) {
    if (!capacity || !vk_resident_enabled()) return;
    ResidentPool *v = &pools[VK_RESIDENT_GEOMETRY], *g = &pools[VK_RESIDENT_GMEM];
    snprintf(buf, capacity,
        " | GPU-resident vtx %llu hit %llu changed %llu new, %.1f MB uploaded"
        " gmem %llu hit %llu changed %llu new, %.1f MB uploaded"
        " busy %llu fallback %llu resident %.1f MB",
        (unsigned long long)v->hits, (unsigned long long)v->refreshes,
        (unsigned long long)v->allocations, (double)v->uploaded_bytes / 1048576.,
        (unsigned long long)g->hits, (unsigned long long)g->refreshes,
        (unsigned long long)g->allocations, (double)g->uploaded_bytes / 1048576.,
        (unsigned long long)(v->busy + g->busy),
        (unsigned long long)(v->fallback + g->fallback),
        (double)(v->bytes + g->bytes) / 1048576.);
    v->hits = v->misses = v->refreshes = v->allocations = v->busy = v->fallback = 0;
    g->hits = g->misses = g->refreshes = g->allocations = g->busy = g->fallback = 0;
    v->uploaded_bytes = v->reused_bytes = v->scanned_bytes = 0;
    g->uploaded_bytes = g->reused_bytes = g->scanned_bytes = 0;
}
