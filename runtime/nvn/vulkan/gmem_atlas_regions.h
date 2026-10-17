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
    for (size_t k = count; k; --k) {
        const GmemAtlasRegion *r = &regions[k-1];
        uint64_t re = (uint64_t)r->guest + r->length;
        if (start < r->guest || (uint64_t)start + len > re) continue;
        uint64_t pos = (uint64_t)r->physical + (start - r->guest);
        if ((pos & 3u) || pos + len > capacity) continue;
        if (memcmp(shadow + pos, guest + start, len)) continue;
        *out = (uint32_t)pos;
        return true;
    }
    return false;
}
