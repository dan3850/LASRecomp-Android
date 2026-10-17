// Persistent, submission-scoped read-only Vulkan GMEM atlas for Android.
// Native guest interval deduplication replaces per-shader GMEM packing.
// Compute writeback and unknown/oversized workloads use the legacy path.
#pragma once
#include "vk.h"
#include "gmem.h"
#include <stddef.h>

VkDescriptorBufferInfo vk_gmem_atlas_get(const GmemPlan *plan,
                                          uint32_t table[(GMAP_MAX + 1) * 4]);
void vk_gmem_atlas_flush(void); // before queue submission
void vk_gmem_atlas_reset(void); // GPU idle
void vk_gmem_atlas_stats_append(char *text, size_t capacity);
