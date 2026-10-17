// LASRecomp Android - GPU-visible GMEM atlas.
//
// This replaces copies of whole GMEM plans with immutable *per-region* atlas
// snapshots. Shader GMAP entries are retargeted to arbitrary offsets in one
// shared mapped VkBuffer. It is NOT a whole-guest-memory mirror, and it does
// not require VK_EXT_external_memory_host.
//
// One persistently allocated slab per Vulkan submission slot, selected by
// pending timeline sequence % 8 (the exec.c command-buffer ring also uses 8).
// Reuse after completion only; writes that change guest data append new
// immutable versions, preserving already-recorded shader reads. Atlas may
// decline any request: exec.c falls back to its existing streaming path.
#include "../../kernel.h"
#include "gmem_atlas.h"
#include "gmem_atlas_regions.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ATLAS_SLOTS 8
#define ATLAS_CAPACITY (8u << 20)
#define ATLAS_REGIONS 2048u

typedef struct {
    VkBuffer buffer;
    VmaAllocation allocation;
    uint8_t *mapped;
    uint8_t *shadow;    // CPU cached copy, never read from WC device memory
    uint32_t capacity, used, dirty_lo, dirty_hi;
    uint32_t nregions;
    GmemAtlasRegion regions[ATLAS_REGIONS];
    uint64_t seq;       // last submission referencing this slab
} GmemAtlas;

static GmemAtlas slabs[ATLAS_SLOTS];
static int enabled = -1, unavailable;
static uint64_t hits, misses, copied_bytes, avoided_bytes, fallback;
static uint64_t busy, total_regions, total_buffers;
static uint64_t copied_regions;

static bool atlas_on(void) {
    if (enabled < 0) {
        const char *v = getenv("LARECOMP_VK_GMEM_ATLAS");
#ifdef __ANDROID__
        enabled = !v || atoi(v) != 0;
#else
        enabled = v && atoi(v) != 0;
#endif
        LOG("[vk-gmem] native read-only atlas %s, 8x8 MiB at most "
            "(LARECOMP_VK_GMEM_ATLAS=%s)\n",
            enabled ? "enabled" : "disabled", v ? v : "unset");
    }
    return enabled != 0 && !unavailable;
}

static bool atlas_allocate(GmemAtlas *a) {
    VkDeviceSize limit = g_vk.props.limits.maxStorageBufferRange;
    uint32_t cap = ATLAS_CAPACITY;
    if (limit < cap) cap = (uint32_t)(limit & ~(VkDeviceSize)255);
    if (cap < 4096) return false;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = cap, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
    VmaAllocationCreateInfo ai = {
        .usage = VMA_MEMORY_USAGE_AUTO,
        .flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT |
                 VMA_ALLOCATION_CREATE_MAPPED_BIT,
    };
    VmaAllocationInfo info = {0};
    VkResult result = vmaCreateBuffer(g_vk.vma, &bi, &ai,
                                      &a->buffer, &a->allocation, &info);
    if (result != VK_SUCCESS || !info.pMappedData) {
        if (a->buffer) vmaDestroyBuffer(g_vk.vma, a->buffer, a->allocation);
        a->buffer = VK_NULL_HANDLE; a->allocation = NULL;
        LOG("[vk-gmem] atlas allocation unavailable (%d); using proven streaming fallback\n", result);
        return false;
    }
    a->shadow = malloc(cap);
    if (!a->shadow) {
        vmaDestroyBuffer(g_vk.vma, a->buffer, a->allocation);
        a->buffer = VK_NULL_HANDLE; a->allocation = NULL;
        return false;
    }
    a->mapped = info.pMappedData;
    a->capacity = cap;
    a->dirty_lo = UINT32_MAX;
    total_buffers++;
    LOG("[vk-gmem] atlas slab allocated %u MiB, slot=%u\n",
        cap >> 20, (unsigned)(a - slabs));
    return true;
}

VkDescriptorBufferInfo vk_gmem_atlas_get(const GmemPlan *plan,
                                         uint32_t table[(GMAP_MAX + 1) * 4]) {
    if (!atlas_on() || !plan || !table || !plan->size)
        return (VkDescriptorBufferInfo){0};
    unsigned count = plan->tab[GMAP_MAX * 4];
    if (!count || count > GMAP_MAX) { fallback++; return (VkDescriptorBufferInfo){0}; }
    uint64_t pending = vk_pending_seq();
    GmemAtlas *a = &slabs[pending % ATLAS_SLOTS];
    if (a->seq != pending) {
        // Never modify a buffer referenced by a previous, unfinished frame.
        if (a->seq && a->seq > vk_completed_seq()) {
            busy++; fallback++;
            return (VkDescriptorBufferInfo){0};
        }
        if (!a->buffer && !atlas_allocate(a)) {
            unavailable = 1; fallback++;
            return (VkDescriptorBufferInfo){0};
        }
        a->seq = pending;
        a->used = a->nregions = 0;
        a->dirty_lo = UINT32_MAX;
        a->dirty_hi = 0;
    }
    if (plan->size > a->capacity) {
        fallback++;
        return (VkDescriptorBufferInfo){0};
    }

    // Phase 1: compute all translations without modifying the buffer or the
    // caller's table. On exhaustion return to legacy code with no partial
    // atlas writes. A single original range always remains contiguous, so
    // the Maxwell shader's gfind() can service vector accesses atomically.
    uint32_t offsets[GMAP_MAX] = {0};
    bool copied[GMAP_MAX] = {0};
    uint64_t needed = 0;
    uint32_t new_entries = 0;
    const uint8_t *guest = (const uint8_t *)(uintptr_t)HEAP_BASE;
    uint64_t heap_bytes = kernel_heap_size();
    for (unsigned i = 0; i < count; ++i) {
        uint32_t first = plan->tab[i*4], len = plan->tab[i*4+1];
        if (!len || (first & 3u) || (len & 3u) ||
            (uint64_t)first + len > heap_bytes) {
            fallback++; return (VkDescriptorBufferInfo){0};
        }
        uint32_t off;
        if (gmem_atlas_region_find(a->regions, a->nregions,
                                   a->shadow, a->capacity, guest, heap_bytes,
                                   first, len, &off)) {
            offsets[i] = off;
            hits++;
            avoided_bytes += len;
        } else {
            uint64_t dest = (uint64_t)a->used + needed;
            if ((dest & 3u) || dest + len > a->capacity ||
                a->nregions + new_entries >= ATLAS_REGIONS) {
                fallback++; return (VkDescriptorBufferInfo){0};
            }
            offsets[i] = (uint32_t)dest;
            copied[i] = true;
            needed += len;
            new_entries++;
        }
    }

    // Phase 2: append new versions to the host-visible Vulkan allocation.
    // The CPU shadow is compared, never the mapped GPU memory. Previously
    // recorded commands can continue reading old snapshots at their offsets.
    for (unsigned i = 0; i < count; ++i) {
        if (!copied[i]) continue;
        uint32_t first = plan->tab[i*4], len = plan->tab[i*4+1];
        uint32_t off = offsets[i];
        memcpy(a->mapped + off, guest + first, len);
        memcpy(a->shadow + off, guest + first, len);
        a->regions[a->nregions++] = (GmemAtlasRegion){first, len, off};
        copied_bytes += len;
        copied_regions++;
    }
    if (needed) {
        if (a->dirty_lo > a->used) a->dirty_lo = a->used;
        a->used += (uint32_t)needed;
        a->dirty_hi = a->used;
    }
    // Retarget every binding into the one atlas buffer, while retaining
    // guest base addresses, sizes, count, and all other metadata.
    memcpy(table, plan->tab, sizeof plan->tab);
    for (unsigned i = 0; i < count; ++i) table[i*4+2] = offsets[i] / 4;
    misses++;
    total_regions += count;
    return (VkDescriptorBufferInfo){a->buffer, 0, a->capacity};
}

void vk_gmem_atlas_flush(void) {
    if (!atlas_on()) return;
    uint64_t pending = vk_pending_seq();
    GmemAtlas *a = &slabs[pending % ATLAS_SLOTS];
    if (a->seq != pending || !a->buffer || a->dirty_lo == UINT32_MAX)
        return;
    VK_CHECK(vmaFlushAllocation(g_vk.vma, a->allocation,
                                a->dirty_lo, a->dirty_hi - a->dirty_lo));
    a->dirty_lo = UINT32_MAX;
}

void vk_gmem_atlas_reset(void) {
    for (unsigned i = 0; i < ATLAS_SLOTS; ++i) {
        GmemAtlas *a = &slabs[i];
        if (a->buffer) vmaDestroyBuffer(g_vk.vma, a->buffer, a->allocation);
        free(a->shadow);
        memset(a, 0, sizeof *a);
    }
    unavailable = 0;
}

void vk_gmem_atlas_stats_append(char *text, size_t capacity) {
    if (!capacity || !atlas_on()) return;
    snprintf(text, capacity,
        " | atlas maps %llu ranges %llu shared %llu new %llu "
        "copied %.1fMB avoided %.1fMB fallback %llu busy %llu",
        (unsigned long long)misses, (unsigned long long)total_regions,
        (unsigned long long)hits, (unsigned long long)copied_regions,
        copied_bytes / 1048576.0, avoided_bytes / 1048576.0,
        (unsigned long long)fallback, (unsigned long long)busy);
    hits = misses = copied_bytes = avoided_bytes = fallback = busy = 0;
    total_regions = copied_regions = 0;
}
