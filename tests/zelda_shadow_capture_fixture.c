/* Real capture header + real vk_surf_use; delayed GPU/retirement endpoints. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef u32 VkImageLayout;
typedef u64 VkPipelineStageFlags2, VkAccessFlags2, VkCommandBuffer;
typedef struct { u8 bytes[256]; } Image;
typedef Image* VkImage;
typedef struct { u8 bytes[256]; int copied; } Buffer;
typedef Buffer* VkBuffer;
typedef Buffer* VmaAllocation;
typedef struct { void* pMappedData; } VmaAllocationInfo;
typedef struct { int sType; u64 size; u32 usage, sharingMode; } VkBufferCreateInfo;
typedef struct { u32 flags, usage; } VmaAllocationCreateInfo;
typedef struct { u32 aspectMask, mipLevel, baseArrayLayer, layerCount; } Subresource;
typedef struct { u32 width, height, depth; } Extent;
typedef struct { u64 bufferOffset; u32 bufferRowLength, bufferImageHeight; Subresource imageSubresource; Extent imageExtent; } VkBufferImageCopy;
typedef struct { int sType; u64 srcStageMask, srcAccessMask, dstStageMask, dstAccessMask; } VkMemoryBarrier2;
typedef struct { int sType; u32 memoryBarrierCount; const VkMemoryBarrier2* pMemoryBarriers; } VkDependencyInfo;
enum { VK_FORMAT_D16_UNORM = 124, VK_FORMAT_X8_D24_UNORM_PACK32, VK_FORMAT_D32_SFLOAT,
       VK_FORMAT_D16_UNORM_S8_UINT = 128, VK_FORMAT_D24_UNORM_S8_UINT, VK_FORMAT_D32_SFLOAT_S8_UINT };
#define VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO 1
#define VK_STRUCTURE_TYPE_MEMORY_BARRIER_2 2
#define VK_STRUCTURE_TYPE_DEPENDENCY_INFO 3
#define VK_BUFFER_USAGE_TRANSFER_DST_BIT 1
#define VK_SHARING_MODE_EXCLUSIVE 1
#define VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT 1
#define VMA_ALLOCATION_CREATE_MAPPED_BIT 2
#define VMA_MEMORY_USAGE_AUTO_PREFER_HOST 1
#define VK_IMAGE_LAYOUT_UNDEFINED 0
#define VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL 2
#define VK_IMAGE_ASPECT_DEPTH_BIT 1
#define VK_IMAGE_ASPECT_STENCIL_BIT 2
#define VK_PIPELINE_STAGE_2_TOP_OF_PIPE_BIT 1
#define VK_PIPELINE_STAGE_2_COPY_BIT 2
#define VK_PIPELINE_STAGE_2_HOST_BIT 4
#define VK_ACCESS_2_TRANSFER_READ_BIT 1
#define VK_ACCESS_2_TRANSFER_WRITE_BIT 2
#define VK_ACCESS_2_HOST_READ_BIT 4
#define VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT 8
#define VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT 16
#define VK_ACCESS_2_SHADER_WRITE_BIT 32
#define VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT 64
#define VK_WHOLE_SIZE (~0ull)
#define VK_OK(call) ((call) == 0)
#define LOG(...) printf(__VA_ARGS__)
#define WARN(...) printf(__VA_ARGS__)
#define WARN_LIMIT(limit, ...) printf(__VA_ARGS__)
typedef struct { u32 vk; int depth; } VkFmt;
typedef struct { VkImage img; u64 gva; u32 w, h, sw, sh, layers, depth3d, levels, wgen, drawn_at;
                 VkFmt f; VkImageLayout layout; u64 stage, access; } Surf;
typedef struct { u64 hash; } VkSh;
static struct { void* vma; u64 alloc_cap; } g_vk = {0, 64ull << 20};
static u32 g_vk_present = 100;
static u64 clock_ns;
static unsigned allocs, frees, ends, barriers, invalidates, copies, host_barriers;
static int alloc_fail, map_fail, retired;
static void (*callback)(void*);
static void* callback_arg;
static struct { VkImage image; VkBuffer buffer; VkBufferImageCopy region; } queued;
static u64 plat_ns(void) { return clock_ns; }
static VkCommandBuffer vk_cmd(void) { return 1; }
static void vk_render_end(void) { ends++; }
static u32 vk_aspect(const VkFmt* f) { return f->depth ? 3 : 0; }
static void vk_barrier(VkCommandBuffer cb, VkImage image, u32 aspect, u64 src_stage, u64 src_access,
                       VkImageLayout from, u64 dst_stage, u64 dst_access, VkImageLayout to) {
    (void)src_stage; (void)src_access; (void)from; (void)dst_stage; (void)dst_access; (void)to;
    assert(cb == 1 && image && aspect == 3); barriers++;
}
#include "surf_use_actual.inc"
static int vmaCreateBuffer(void* vma, const VkBufferCreateInfo* bi, const VmaAllocationCreateInfo* ai,
                            VkBuffer* out, VmaAllocation* allocation, VmaAllocationInfo* info) {
    (void)vma; assert(bi->size <= 256 && bi->usage == VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    assert(ai->flags == 3 && ai->usage == VMA_MEMORY_USAGE_AUTO_PREFER_HOST);
    if (alloc_fail) return -1;
    *allocation = *out = calloc(1, sizeof **out); assert(*out); allocs++;
    info->pMappedData = map_fail ? NULL : (*out)->bytes; return 0;
}
static void vmaDestroyBuffer(void* vma, VkBuffer b, VmaAllocation a) {
    (void)vma; assert(a == b); frees++; free(b);
}
static int vmaInvalidateAllocation(void* vma, VmaAllocation a, u64 off, u64 size) {
    (void)vma; assert(retired && a->copied && off == 0 && size == VK_WHOLE_SIZE); invalidates++; return 0;
}
static void rec_CmdCopyImageToBuffer(VkCommandBuffer cb, VkImage image, VkImageLayout layout, VkBuffer buffer,
                                    u32 n, const VkBufferImageCopy* region) {
    assert(cb == 1 && layout == VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL && n == 1 && !queued.buffer);
    assert(region->imageSubresource.aspectMask == VK_IMAGE_ASPECT_DEPTH_BIT);
    assert(region->imageSubresource.mipLevel == 0 && region->imageSubresource.baseArrayLayer == 0);
    assert(region->imageSubresource.layerCount == 2 && region->imageExtent.width == 4 && region->imageExtent.height == 3);
    assert(region->imageExtent.depth == 1 && !region->bufferOffset && !region->bufferRowLength && !region->bufferImageHeight);
    queued.image = image; queued.buffer = buffer; queued.region = *region; copies++;
}
static void rec_CmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo* di) {
    assert(cb == 1 && queued.buffer && di->memoryBarrierCount == 1);
    const VkMemoryBarrier2* mb = di->pMemoryBarriers;
    assert(mb->srcStageMask == VK_PIPELINE_STAGE_2_COPY_BIT && mb->srcAccessMask == VK_ACCESS_2_TRANSFER_WRITE_BIT);
    assert(mb->dstStageMask == VK_PIPELINE_STAGE_2_HOST_BIT && mb->dstAccessMask == VK_ACCESS_2_HOST_READ_BIT);
    host_barriers++;
}
static void vk_defer_call(void (*fn)(void*), void* arg) { assert(!callback); callback = fn; callback_arg = arg; }
#include "shadow_capture.h"
static void retire(u32 bpp) {
    assert(callback && queued.buffer && !queued.buffer->copied);
    size_t bytes = queued.region.imageExtent.width * queued.region.imageExtent.height * 2 * bpp;
    memcpy(queued.buffer->bytes, queued.image->bytes, bytes); queued.buffer->copied = 1;
    retired = 1; callback(callback_arg); retired = 0;
    callback = NULL; callback_arg = NULL; memset(&queued, 0, sizeof queued);
}
int main(int argc, char** argv) {
    assert(argc == 2);
    Image image = {0};
    Surf t = {.img = &image, .gva = 0x123000, .w = 4, .h = 3, .sw = 4, .sh = 3, .layers = 2,
              .depth3d = 0, .levels = 1, .wgen = 3, .drawn_at = 100,
              .f = {VK_FORMAT_D24_UNORM_S8_UINT, 1}, .layout = 3, .stage = 8,
              .access = VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT};
    u32 r[0x1000] = {0}, tic[8] = {123}, tsc[8] = {456}; VkSh shader = {0xabcdef};
    r[0x4ba] = r[0x4b3] = r[0x35f] = 1; r[0x4c3] = 0x201;
    unsetenv("SNX_SHADOW_CAPTURE_DIR"); snx_shadow_init();
    snx_shadow_note(&t, &shader, NULL, r, 0); snx_shadow_capture(&shader, 4, 7, &t, tic, tsc);
    assert(!allocs && !ends && !barriers && !copies && !snx_shadow_enabled);
    setenv("SNX_SHADOW_CAPTURE_DIR", argv[1], 1); snx_shadow_init();
    snx_shadow_note(&t, &shader, NULL, r, 0);
    clock_ns = 14000000000ull; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(!allocs);
    clock_ns += 1000000000ull; alloc_fail = 1; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc);
    assert(!allocs && !snx_shadow_count); alloc_fail = 0;
    clock_ns += 15000000000ull; map_fail = 1; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc);
    assert(allocs == 1 && frees == 1 && !snx_shadow_count); map_fail = 0;
    for (u32 capture = 0; capture < 3; capture++) {
        clock_ns += 15000000000ull;
        t.depth3d = 2; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(!callback); t.depth3d = 0;
        t.levels = 2; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(!callback); t.levels = 1;
        t.layers = 17; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(!callback); t.layers = 2;
        t.sw = 8192; t.sh = 8192; snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(!callback); t.sw = 4; t.sh = 3;
        u32 bpp = capture == 1 ? 2 : 4;
        t.f.vk = capture == 0 ? VK_FORMAT_D24_UNORM_S8_UINT : capture == 1 ? VK_FORMAT_D16_UNORM : VK_FORMAT_D32_SFLOAT;
        for (u32 j = 0; j < 24; j++) {
            if (capture == 0) { u32 v = j < 12 ? 0xff000000u : 0xffffffffu; memcpy(image.bytes + 4 * j, &v, 4); }
            if (capture == 1) { uint16_t v = j < 12 ? 0 : 65535; memcpy(image.bytes + 2 * j, &v, 2); }
            if (capture == 2) { float v = j < 12 ? 0.25f : 0.75f; memcpy(image.bytes + 4 * j, &v, 4); }
        }
        snx_shadow_capture(&shader, 4, 7, &t, tic, tsc);
        assert(callback && invalidates == capture);
        assert(t.layout == 3 && t.stage == 8 && t.access == VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT);
        unsigned was = allocs; clock_ns += 15000000000ull;
        snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(allocs == was); /* one pending buffer */
        tic[0] = 789; /* queued metadata must own its values */
        retire(bpp); assert(!snx_shadow_pending);
    }
    unsigned was = allocs; clock_ns += 15000000000ull;
    snx_shadow_capture(&shader, 4, 7, &t, tic, tsc); assert(allocs == was);
    assert(allocs == frees && copies == 3 && invalidates == 3 && host_barriers == 3 && barriers == 6);
    puts("SHADOW_OK off_no_work=1 layers=2 retirement_before_read=1 state_restored=1 bounded=1");
    return 0;
}
