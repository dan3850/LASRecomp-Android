// Packed guest storage ranges shared by graphics snapshots and compute writeback.
// No Vulkan calls: the layout can be tested without a GPU or game files.
#pragma once
#include <string.h>
#include "../maxwell/shader.h"

typedef struct { uint64_t addr, size; } GmemRange;
typedef struct {
    uint32_t tab[(GMAP_MAX + 1) * 4]; // heap offset, byte length, packed word offset, reserved
    uint64_t size;
} GmemPlan;

static inline bool gmem_plan(GmemPlan *p, const GmemRange *r, unsigned n,
                             uint64_t base, uint64_t heap, uint64_t limit) {
    GmemRange sorted[GMAP_MAX];
    unsigned count = 0;
    memset(p, 0, sizeof *p);
    if (n > GMAP_MAX || heap > UINT32_MAX) return false;
    for (unsigned i = 0; i < n; ++i) {
        if (!r[i].size || r[i].addr < base || r[i].addr - base >= heap ||
            r[i].size > heap - (r[i].addr - base)) continue;
        uint64_t lo = (r[i].addr - base) & ~3ull;
        uint64_t hi = (r[i].addr - base + r[i].size + 3) & ~3ull;
        if (hi > heap) hi = heap & ~3ull;
        if (hi <= lo) continue;
        unsigned j = count++;
        while (j && sorted[j - 1].addr > lo) { sorted[j] = sorted[j - 1]; --j; }
        sorted[j] = (GmemRange){lo, hi - lo};
    }
    unsigned merged = 0;
    for (unsigned i = 0; i < count; ++i) {
        if (merged && sorted[i].addr <= sorted[merged - 1].addr + sorted[merged - 1].size) {
            uint64_t end = sorted[i].addr + sorted[i].size;
            if (end > sorted[merged - 1].addr + sorted[merged - 1].size)
                sorted[merged - 1].size = end - sorted[merged - 1].addr;
        } else sorted[merged++] = sorted[i];
    }
    for (unsigned i = 0; i < merged; ++i) {
        if (p->size > limit || sorted[i].size > limit - p->size) {
            memset(p, 0, sizeof *p);
            return false; // never publish a partial table
        }
        p->tab[i * 4] = (uint32_t)sorted[i].addr;
        p->tab[i * 4 + 1] = (uint32_t)sorted[i].size;
        p->tab[i * 4 + 2] = (uint32_t)(p->size / 4);
        p->size += sorted[i].size;
    }
    p->tab[GMAP_MAX * 4] = merged;
    return true;
}

// Copy only bytes changed by the shader, preserving CPU-owned neighbouring
// bytes in the same packed range. Call only AFTER GPU completion + invalidation.
static inline void gmem_apply(uint8_t *guest, const uint8_t *before,
                              const uint8_t *after, size_t size) {
    for (size_t i = 0; i < size;) {
        if (before[i] == after[i]) { ++i; continue; }
        size_t start = i++;
        while (i < size && before[i] != after[i]) ++i;
        memcpy(guest + start, after + start, i - start);
    }
}
