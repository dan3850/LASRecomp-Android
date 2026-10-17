// Portable decision policy for Vulkan render-target image barriers.
// The exact affected images are known for copy/resolve/snapshot operations;
// the fallback is retained if any resource/aspect is unknown.
#pragma once
#include <stdbool.h>
#include <stdint.h>
static inline bool las_rt_copy_scope_allowed(bool enabled,
 uint64_t source, uint64_t dest,
 uint32_t source_aspects, uint32_t dest_aspects) {
 return enabled && source && dest && source_aspects && dest_aspects;
}
static inline uint32_t las_rt_copy_image_count(
 uint64_t source, uint64_t dest) {
 return source == dest ? 1u : 2u;
}
static inline uint32_t las_rt_copy_aspects(
 uint64_t source, uint64_t dest,
 uint32_t source_aspects, uint32_t dest_aspects, uint32_t index) {
 return source == dest ? (source_aspects|dest_aspects)
                       : index == 0 ? source_aspects : dest_aspects;
}
