// Four-way reuse policy for immutable guest upload snapshots.
// Only snapshots from the same submission and CPU-write generation may be reused.
#pragma once
#include <stdint.h>

#define LAS_GCOPY_WAYS 4u

typedef struct {
    uint64_t addr, size, seq;
} LasGuestCopyKey;

static inline unsigned las_gcopy_bucket(uint64_t addr, unsigned buckets) {
    uint64_t h = addr * 0x9E3779B97F4A7C15ull;
    return (unsigned)(h ^ (h >> 32)) & (buckets - 1u);
}

static inline int las_gcopy_find(const LasGuestCopyKey *entries, unsigned ways,
                                  uint64_t seq, uint64_t addr, uint64_t size) {
    for (unsigned i = 0; i < ways; ++i)
        if (entries[i].seq == seq && entries[i].addr == addr && entries[i].size >= size)
            return (int)i;
    return -1;
}

static inline unsigned las_gcopy_victim(const LasGuestCopyKey *entries, unsigned ways,
                                         uint64_t seq, unsigned next) {
    for (unsigned i = 0; i < ways; ++i)
        if (entries[i].seq != seq) return i;
    return next % ways;
}
