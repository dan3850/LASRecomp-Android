// Render-target copy scheduler: per-image barriers rather than global
// barriers for image-to-image copies and snapshots. All other hazards retain
// the original full barriers. Off switch for independent A/B verification.
#pragma once
#include "vk.h"
#include <stddef.h>
void vk_rt_prepare_copy(VkCommandBuffer cb, VkImage source, VkImage target,
                        VkImageAspectFlags source_aspects, VkImageAspectFlags target_aspects);
void vk_rt_copy_stats(char *buffer, size_t capacity);
