// CPU byte-exact validation of a persistent GPU-visible atlas mapping.
// The game can write guest memory without tracked generations.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
// Each GPU consumer extends the lifetime of its source allocation.
// The allocation may be recycled only once the timeline has completed that
// consumer's submission, not merely its original writer's submission.
static inline bool gmem_atlas_slot_reclaimable(
        uint64_t last_use_seq, uint64_t completed_seq) {
    return !last_use_seq || last_use_seq <= completed_seq;
}

static inline bool gmem_atlas_saved_plan_matches(
    const uint32_t *original, const uint32_t *mapped, uint32_t count,
    const uint8_t *shadow, size_t capacity,
    const uint8_t *guest, size_t guest_size) {
    if (!original || !mapped || !shadow || !guest || !count || count > 35) return false;
    for (uint32_t i=0; i<count; ++i) {
        uint64_t first=original[i*4], bytes=original[i*4+1];
        uint64_t off=(uint64_t)mapped[i*4+2]*4;
        if (!bytes || (bytes & 3u) || (first & 3u) ||
            first != mapped[i*4] || bytes != mapped[i*4+1] ||
            first+bytes > guest_size || off+bytes > capacity ||
            memcmp(guest+first, shadow+off, (size_t)bytes)) return false;
    }
    return true;
}
