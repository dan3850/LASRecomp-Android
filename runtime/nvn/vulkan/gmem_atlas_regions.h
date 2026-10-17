// Pure-C covered-range lookup for the shared GPU GMEM atlas.
// No Vulkan API or private game data: easy to exercise under sanitizers.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    uint32_t guest;     // guest heap-relative byte offset (4-byte aligned)
    uint32_t length;    // immutable region length
    uint32_t physical;  // atlas byte offset; previous versions are not overwritten
} GmemAtlasRegion;

#define GMEM_ATLAS_PAGE_SHIFT 16u
#define GMEM_ATLAS_BUCKET_COUNT 512u

static inline uint32_t gmem_atlas_page_bucket(uint32_t heap_offset) {
    uint32_t page = heap_offset >> GMEM_ATLAS_PAGE_SHIFT;
    return (page * UINT32_C(2654435761)) & (GMEM_ATLAS_BUCKET_COUNT - 1);
}
static inline uint32_t gmem_atlas_region_pages(uint32_t first, uint32_t len) {
    if (!len) return 0;
    return (uint32_t)(((uint64_t)first + len - 1) >> GMEM_ATLAS_PAGE_SHIFT)
         - (first >> GMEM_ATLAS_PAGE_SHIFT) + 1;
}

// A bucket already identifies likely candidates. Verify exact guest contents
// against a CPU-cached immutable snapshot to protect untracked guest writes.
static inline bool gmem_atlas_region_matches(
        const GmemAtlasRegion *r,
        const uint8_t *shadow, size_t capacity,
        const uint8_t *guest, size_t guest_bytes,
        uint32_t start, uint32_t len, uint32_t *out) {
    if (!r || !shadow || !guest || !out || !len ||
        (start & 3u) || (len & 3u) ||
        (uint64_t)start + len > guest_bytes) return false;
    uint64_t end = (uint64_t)r->guest + r->length;
    if (start < r->guest || (uint64_t)start + len > end) return false;
    uint64_t pos = (uint64_t)r->physical + (start - r->guest);
    if ((pos & 3u) || pos + len > capacity) return false;
    if (memcmp(shadow + pos, guest + start, len)) return false;
    *out = (uint32_t)pos;
    return true;
}

// Find newest byte-identical snapshot that fully contains [start, start+len).
// The immutable CPU shadow avoids reading mapped write-combined GPU memory.
// Returns false (and leaves out unchanged) if nothing covers all requested
// bytes, including when the guest changed since the earlier snapshot.
static inline bool gmem_atlas_region_find(
        const GmemAtlasRegion *regions, size_t count,
        const uint8_t *shadow, size_t capacity,
        const uint8_t *guest, size_t guest_bytes,
        uint32_t start, uint32_t len, uint32_t *out) {
    if (!regions || !shadow || !guest || !out || !len ||
        (start & 3u) || (len & 3u) ||
        (uint64_t)start + len > guest_bytes) return false;
    for (size_t k = count; k; --k)
        if (gmem_atlas_region_matches(&regions[k-1], shadow, capacity,
                                      guest, guest_bytes, start, len, out))
            return true;
    return false;
}
