#include "../../kernel.h"
#include "rt_graph.h"
#include <stdlib.h>
#include <stdio.h>

static int on = -1;
static uint64_t scoped, legacy;

void vk_rt_prepare_copy(VkCommandBuffer cb, VkImage src, VkImage dst,
                        VkImageAspectFlags sa, VkImageAspectFlags da) {
    if (on < 0) {
        const char *v = getenv("LARECOMP_VK_RT_SCOPE");
#ifdef __ANDROID__
        on = !v || atoi(v) != 0;
#else
        on = v && atoi(v) != 0;
#endif
        LOG("[vk-rt] per-image copy dependencies %s\n", on ? "on" : "off");
    }
    if (!on || !src || !dst || !sa || !da) {
        legacy++;
        vk_full_barrier(cb);
        return;
    }
    // All earlier read/write accesses to these exact images are ordered before
    // transfer reads/writes, even if the earlier access was fragment/compute.
    // Unrelated Vulkan images and buffers need not wait at this dependency.
    // Whole subresource ranges, including depth/stencil aspects, deliberately
    // keep the first iteration conservative about levels and layers.
    VkImageMemoryBarrier2 dep[2];
    uint32_t n = src == dst ? 1 : 2;
    for (uint32_t i = 0; i < n; ++i) {
        VkImage img = i == 0 ? src : dst;
        VkImageAspectFlags aspect = (src == dst) ? sa | da : i == 0 ? sa : da;
        dep[i] = (VkImageMemoryBarrier2){
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2,
            .srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT,
            .srcAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT,
            .dstStageMask = VK_PIPELINE_STAGE_2_TRANSFER_BIT,
            .dstAccessMask = VK_ACCESS_2_TRANSFER_READ_BIT | VK_ACCESS_2_TRANSFER_WRITE_BIT,
            .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
            .newLayout = VK_IMAGE_LAYOUT_GENERAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = img,
            .subresourceRange = {aspect, 0, VK_REMAINING_MIP_LEVELS, 0, VK_REMAINING_ARRAY_LAYERS},
        };
    }
    VkDependencyInfo di = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO,
        .imageMemoryBarrierCount = n, .pImageMemoryBarriers = dep};
    vkCmdPipelineBarrier2(cb, &di);
    scoped++;
}
void vk_rt_copy_stats(char *dst, size_t capacity) {
    if (!capacity) return;
    snprintf(dst, capacity, " | RT copy dependencies scoped %llu full %llu",
             (unsigned long long)scoped, (unsigned long long)legacy);
    scoped = legacy = 0;
}
