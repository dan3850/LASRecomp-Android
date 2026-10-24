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
static struct { VkImage image; VkBuffer buffer; VkBufferImageCopy region; } queued[2];
static unsigned queued_n;
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
    assert(cb == 1 && layout == VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL && n == 1 && queued_n < 2);
    assert(region->imageSubresource.aspectMask == VK_IMAGE_ASPECT_DEPTH_BIT);
    assert(region->imageSubresource.mipLevel == 0 && region->imageSubresource.baseArrayLayer == 0);
    assert(region->imageSubresource.layerCount == 1 && region->imageExtent.width == 4 && region->imageExtent.height == 3);
    assert(region->imageExtent.depth == 1 && region->bufferOffset == 48 * queued_n);
    assert(!region->bufferRowLength && !region->bufferImageHeight);
    queued[queued_n].image = image; queued[queued_n].buffer = buffer; queued[queued_n].region = *region;
    queued_n++; copies++;
}
static void rec_CmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo* di) {
    assert(cb == 1 && queued_n == 2 && di->memoryBarrierCount == 1);
    const VkMemoryBarrier2* mb = di->pMemoryBarriers;
    assert(mb->srcStageMask == VK_PIPELINE_STAGE_2_COPY_BIT && mb->srcAccessMask == VK_ACCESS_2_TRANSFER_WRITE_BIT);
    assert(mb->dstStageMask == VK_PIPELINE_STAGE_2_HOST_BIT && mb->dstAccessMask == VK_ACCESS_2_HOST_READ_BIT);
    host_barriers++;
}
static void vk_defer_call(void (*fn)(void*), void* arg) { assert(!callback); callback = fn; callback_arg = arg; }
#include "effect_depth.h"
static void retire(void) {
    assert(callback && queued_n == 2);
    for (unsigned i = 0; i < 2; i++) {
        assert(queued[i].buffer == queued[0].buffer);
        memcpy(queued[i].buffer->bytes + queued[i].region.bufferOffset, queued[i].image->bytes, 48);
    }
    queued[0].buffer->copied = 1;
    retired = 1; callback(callback_arg); retired = 0;
    callback = NULL; callback_arg = NULL; queued_n = 0; memset(queued, 0, sizeof queued);
}
int main(int argc, char** argv) {
    assert(argc == 2);
    Image images[2] = {0};
    Surf at = {.img = &images[0], .gva = 0x123000, .w = 4, .h = 3, .sw = 4, .sh = 3, .layers = 1,
               .depth3d = 0, .levels = 1, .wgen = 3, .f = {VK_FORMAT_D24_UNORM_S8_UINT, 1},
               .layout = 3, .stage = 8, .access = VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT};
    Surf sample = at; sample.img = &images[1]; sample.gva = 0x124000; sample.wgen = 2;
    sample.layout = 4; sample.stage = 16; sample.access = 0;
    Surf old_at = at, old_sample = sample;
    u32 r[0x1000] = {0}, tic[8] = {123}, tsc[8] = {456};
    VkSh shader = {0x86d5a3f915a6795full};
    unsetenv("SNX_EFFECT_DEPTH_DIR"); snx_effect_depth_init();
    snx_effect_depth_capture(NULL, 4, 0, NULL, NULL, NULL, NULL, NULL);
    assert(!allocs && !ends && !barriers && !copies && !snx_effect_depth_on);
    setenv("SNX_EFFECT_DEPTH_DIR", "relative", 1); snx_effect_depth_init(); assert(!snx_effect_depth_on);
    setenv("SNX_EFFECT_DEPTH_DIR", argv[1], 1); snx_effect_depth_init();
    clock_ns = 14000000000ull;
    snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); assert(!allocs);
    clock_ns = 15000000000ull;
    VkSh other = {123};
    snx_effect_depth_capture(&other, 4, 0, &at, &sample, tic, tsc, r);
    snx_effect_depth_capture(&shader, 0, 0, &at, &sample, tic, tsc, r);
    snx_effect_depth_capture(&shader, 4, 1, &at, &sample, tic, tsc, r);
    snx_effect_depth_capture(&shader, 4, 0, &at, &at, tic, tsc, r);
    snx_effect_depth_capture(&shader, 4, 0, NULL, &sample, tic, tsc, r); assert(!allocs);
    sample.sw = 3; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); sample = old_sample;
    sample.layers = 2; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); sample = old_sample;
    sample.levels = 2; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); sample = old_sample;
    sample.depth3d = 2; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); sample = old_sample;
    sample.layout = 0; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); sample = old_sample;
    sample.f.vk = VK_FORMAT_D32_SFLOAT; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); sample = old_sample;
    g_vk.alloc_cap = 95; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); g_vk.alloc_cap = 64ull << 20;
    at.sw = sample.sw = 8192; at.sh = sample.sh = 8192;
    snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); at = old_at; sample = old_sample;
    assert(!allocs && !ends);
    alloc_fail = 1; snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); alloc_fail = 0;
    assert(!allocs && !snx_effect_depth_count);
    clock_ns += 15000000000ull; map_fail = 1;
    snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); map_fail = 0;
    assert(allocs == 1 && frees == 1 && !snx_effect_depth_count);
    for (unsigned capture = 0; capture < 3; capture++) {
        clock_ns += 15000000000ull;
        at.f.vk = sample.f.vk = capture == 2 ? VK_FORMAT_D32_SFLOAT : VK_FORMAT_D24_UNORM_S8_UINT;
        for (unsigned j = 0; j < 12; j++) {
            u32 av = 0xff000000u | (j == 0 ? 0 : 0x800000), bv = 0x11000000u | (j == 0 ? 0 : 0x800000);
            if (capture == 1 && j == 5) bv = 0x11ffffffu;
            if (capture == 2) {
                float a = j == 0 ? 0 : .25f, b = j == 0 ? 0 : .75f;
                memcpy(&av, &a, 4); memcpy(&bv, &b, 4);
            }
            memcpy(images[0].bytes + j * 4, &av, 4); memcpy(images[1].bytes + j * 4, &bv, 4);
        }
        old_at = at; old_sample = sample;
        tic[0] = 123; r[0x64f] = 0x181d;
        snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r);
        assert(callback && invalidates == capture);
        assert(!memcmp(&at, &old_at, sizeof at) && !memcmp(&sample, &old_sample, sizeof sample));
        assert(r[0x64f] == 0x181d && tic[0] == 123 && tsc[0] == 456);
        tic[0] = 789; r[0x64f] = 0;
        unsigned was = allocs; clock_ns += 15000000000ull;
        snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); assert(allocs == was);
        retire(); assert(!snx_effect_depth_pending);
    }
    unsigned was = allocs; clock_ns += 15000000000ull;
    snx_effect_depth_capture(&shader, 4, 0, &at, &sample, tic, tsc, r); assert(allocs == was);
    /* Each of the four real vk_surf_use calls asks to end any open pass;
     * the render backend makes repeated requests no-ops after the first. */
    assert(allocs == frees && copies == 6 && ends == 15 && invalidates == 3 && host_barriers == 3 && barriers == 12);
    puts("EFFECT_DEPTH_OK off_no_work=1 paired=1 retirement_before_read=1 state_restored=1 bounded=1");
    return 0;
}
