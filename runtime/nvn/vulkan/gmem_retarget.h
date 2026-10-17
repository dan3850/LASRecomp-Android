// Rebind a smaller logical guest GMEM map to a previously packed superset.
// The caller must separately ensure same-submission, same guest-write epoch,
// and read-only immutable VkBuffer contents. This only remaps table offsets:
// no CPU/GPU data movement. Reuse cannot cross an uncovered guest interval.
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "gmem.h"

static inline bool gmem_retarget_covered(const GmemPlan *resident, const GmemPlan *need,
                                         uint32_t table[(GMAP_MAX + 1) * 4]) {
    if (!resident || !need || !resident->size || !need->size ||
        resident->size < need->size) return false;
    const uint32_t nr = resident->tab[GMAP_MAX * 4], nn = need->tab[GMAP_MAX * 4];
    if (!nr || !nn || nr > GMAP_MAX || nn > GMAP_MAX) return false;
    uint32_t new_offset[GMAP_MAX] = {0};
    for (unsigned i = 0; i < nn; ++i) {
        uint64_t first = need->tab[4*i], len = need->tab[4*i+1];
        if (!len || first + len > UINT32_MAX + 1ull) return false;
        bool found = false;
        for (unsigned j = 0; j < nr; ++j) {
            uint64_t a = resident->tab[4*j], b = a + resident->tab[4*j+1];
            if (first < a || first + len > b) continue;
            uint64_t off = (uint64_t)resident->tab[4*j+2] * 4 + first - a;
            if (off + len > resident->size || (off & 3) || off / 4 > UINT32_MAX)
                return false;
            new_offset[i] = (uint32_t)(off / 4);
            found = true; break;
        }
        if (!found) return false;
    }
    memcpy(table, need->tab, sizeof need->tab);
    for (unsigned i = 0; i < nn; ++i) table[4*i+2] = new_offset[i];
    return true;
}
