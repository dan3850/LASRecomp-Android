// Vulkan-free compatibility policy for deferred full-image copies.
// Copy aliases only become valid after a COMPLETE copy of equal-format images.
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    uint32_t format, width, height, aspect, base_type;
    uint32_t levels, layers, depth, samples;
    bool gpu_owned, presented, has_image;
} RtAliasDesc;
static inline bool rt_alias_compatible(RtAliasDesc a, RtAliasDesc b) {
    return a.has_image && b.has_image && a.gpu_owned && b.gpu_owned &&
           !a.presented && !b.presented &&
           a.format == b.format && a.aspect == b.aspect &&
           a.width == b.width && a.height == b.height &&
           a.base_type == b.base_type &&
           a.levels == 1 && b.levels == 1 && a.layers == 1 && b.layers == 1 &&
           a.depth == 1 && b.depth == 1 && a.samples == 1 && b.samples == 1;
}
static inline uint32_t rt_alias_needed_aspects(uint32_t aspects, uint32_t overwritten) {
    return aspects & ~overwritten;
}
