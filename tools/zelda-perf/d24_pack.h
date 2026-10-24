/* SPDX-License-Identifier: MIT
 * Qualified D24/S8 images can now feed existing byte-exact memory transfers.
 * Included once by surface.c after its layout helpers, under vk_lock.
 */
#include <stdlib.h>
#include <string.h>

static int snx_d24_pack_on;
static u64 snx_d24_packed, snx_d24_pixels, snx_d24_failures, snx_d24_conversions, snx_d24_reused;
static u64 snx_d24_stale, snx_d24_partial;
static unsigned snx_d24_states;
/* This workspace is never published to guest ownership and never borrowed by
 * DMA/blit/texture code. Keep one allocation; normal deferred retirement
 * protects its old commands when growth replaces it. */
static VkOwnRes* snx_d24_work;
static struct { VkImage image; u64 sequence; u32 epoch, wgen, format, w, h; int valid; } snx_d24_cache;

void snx_d24_pack_init(void) {
    const char* value = getenv("SNX_VK_D24_PACK");
    int requested = value && !strcmp(value, "1");
    int supported = requested ? vk_tc_d24_pack_supported() : 0;
    snx_d24_pack_on = requested && supported;
    if (requested && !supported) WARN("D24 copy correction inactive: internal conversion shader is stale or invalid\n");
    if (snx_perf_on)
        LOG("SNX_D24_PACK_META_V1 {\"requested\":%d,\"shader_supported\":%d,\"enabled\":%d,"
            "\"integration\":2,\"gpu_overlay_only\":1,\"cpu_writeback\":0,\"isolated_work\":1,"
            "\"exact_bits\":1,\"stencil_preserved\":1,\"unscaled_only\":1,\"one_layer\":1,\"recorder_extra_waits\":0}\n",
            requested, supported, snx_d24_pack_on);
}

static u64 snx_d24_up(u64 value, u64 alignment) { return (value + alignment - 1) / alignment * alignment; }

/* Narrow support: the two explicit 32-bit packed ZT layouts whose host
 * image is D24/S8, one unscaled level/layer. Other layouts retain old policy. */
static int snx_d24_pack_eligible(const Surf* s) {
    if (!snx_d24_pack_on || !s || !s->is_rt || !s->f.depth || !s->f.stencil || s->f.bpp != 4 ||
        s->f.vk != VK_FORMAT_D24_UNORM_S8_UINT || (s->fkey != 0x10014 && s->fkey != 0x10016) ||
        !s->w || !s->h || s->sw != s->w || s->sh != s->h || s->levels != 1 || s->layers != 1 ||
        s->volume || s->bd || s->layout == VK_IMAGE_LAYOUT_UNDEFINED || (s->bl && (s->w & 3)) ||
        (!s->bl && s->pitch != (u64)s->w * 4)) return 0;
    u64 pitch = snx_d24_up((u64)s->w * 4, 16), sp = snx_d24_up(s->w, 4);
    u64 alignment = g_vk.props.limits.minStorageBufferOffsetAlignment;
    if (alignment < 4) alignment = 4;
    u64 planes = (pitch + sp) * s->h, packed_at = snx_d24_up(planes, alignment), packed = pitch * s->h;
    return planes <= g_vk.props.limits.maxStorageBufferRange && packed <= g_vk.props.limits.maxStorageBufferRange &&
           packed_at + packed <= g_vk.alloc_cap && packed_at + packed <= (64ull << 20) &&
           (s->w + 63ull) / 64 <= g_vk.props.limits.maxComputeWorkGroupCount[0] &&
           s->h <= g_vk.props.limits.maxComputeWorkGroupCount[1];
}

/* Only a wholly contained, still-pending image can overlay a GPU copy.
 * A recorded memory write, including a physical alias, makes the image stale.
 * Do not read it back or replace newer owned bytes to obtain a partial copy. */
static int snx_d24_pack_pending(const Surf* s, u64 gva, u64 size) {
    if (!snx_d24_pack_eligible(s) || s->mem_wgen == s->wgen) return 0;
    u64 bytes = rt_bytes(s);
    if (s->gva < gva || s->gva - gva > size || bytes > size - (s->gva - gva)) {
        snx_d24_partial++; return 0;
    }
    if (gpu_mem_dirty_since(s->gw, s->gva, bytes)) { snx_d24_stale++; return 0; }
    return 1;
}

static VkBuffer snx_d24_workspace(u64 need) {
    if (snx_d24_work && snx_d24_work->size >= need) return snx_d24_work->buf;
    u64 cap = 4ull << 20;
    while (cap < need) cap *= 2;
    if (cap > g_vk.alloc_cap) cap = g_vk.alloc_cap;
    if (cap < need) return VK_NULL_HANDLE;
    VkOwnRes* next = vk_own_res_new(cap);
    if (!next) return VK_NULL_HANDLE;
    if (snx_d24_work) vk_own_res_unref(snx_d24_work);
    snx_d24_work = next;
    snx_d24_cache.valid = 0;
    return next->buf;
}

static int snx_d24_pack_record(VkCommandBuffer cb, Surf* s, VkBuffer out, u64 out_at) {
    /* The unchanged GOB kernel moves complete 16-byte runs. Keep it away
     * from partial runs and unaligned ranges instead of changing padding. */
    if (out_at & (s->bl ? 15u : 3u)) { snx_d24_failures++; return 0; }
    u32 pitch = (u32)snx_d24_up((u64)s->w * 4, 16), sp = (u32)snx_d24_up(s->w, 4);
    u64 depth_bytes = (u64)pitch * s->h, planes = depth_bytes + (u64)sp * s->h;
    u64 alignment = g_vk.props.limits.minStorageBufferOffsetAlignment;
    if (alignment < 4) alignment = 4;
    u64 packed_at = snx_d24_up(planes, alignment);
    VkBuffer scratch = snx_d24_workspace(packed_at + depth_bytes);
    if (!scratch || scratch == out) { snx_d24_failures++; return 0; }
    int cached = snx_d24_cache.valid && snx_d24_cache.image == s->img &&
                 snx_d24_cache.sequence == s->wseq && snx_d24_cache.wgen == s->wgen &&
                 snx_d24_cache.epoch == g_vk_surf_epoch && snx_d24_cache.format == s->fkey &&
                 snx_d24_cache.w == s->w && snx_d24_cache.h == s->h;
    int ok = 1;
    if (!cached) {
        snx_d24_cache.valid = 0;
        /* A prior export may still read the retained packed rows. Order every
         * reuse before overwriting the input planes or the packed output. */
        VkMemoryBarrier2 reuse = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
            .srcStageMask = VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT | VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT,
            .srcAccessMask = VK_ACCESS_2_TRANSFER_READ_BIT | VK_ACCESS_2_TRANSFER_WRITE_BIT |
                             VK_ACCESS_2_SHADER_STORAGE_READ_BIT | VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT,
            .dstStageMask = VK_PIPELINE_STAGE_2_COPY_BIT, .dstAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT};
        VkDependencyInfo dep = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .memoryBarrierCount = 1,
                                .pMemoryBarriers = &reuse};
        rec_CmdPipelineBarrier2(cb, &dep);
        vk_surf_use(cb, s, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_COPY_BIT,
                    VK_ACCESS_2_TRANSFER_READ_BIT);
        VkBufferImageCopy c[2] = {
            {.bufferRowLength = pitch / 4, .imageSubresource = {VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, 1},
             .imageExtent = {s->w, s->h, 1}},
            {.bufferOffset = depth_bytes, .bufferRowLength = sp,
             .imageSubresource = {VK_IMAGE_ASPECT_STENCIL_BIT, 0, 0, 1}, .imageExtent = {s->w, s->h, 1}}};
        rec_CmdCopyImageToBuffer(cb, s->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, scratch, 2, c);
        vk_bl_barrier(cb, 1);
        ok = vk_tc_pack_d24(cb, s->fkey == 0x10014, s->w, s->h, scratch, 0, pitch,
                                depth_bytes, sp, scratch, packed_at, pitch);
        vk_bl_barrier(cb, 0); /* also orders shader writes before later HOST reads */
        if (ok) {
            snx_d24_cache.image = s->img; snx_d24_cache.sequence = s->wseq;
            snx_d24_cache.wgen = s->wgen; snx_d24_cache.epoch = g_vk_surf_epoch;
            snx_d24_cache.format = s->fkey; snx_d24_cache.w = s->w; snx_d24_cache.h = s->h;
            snx_d24_cache.valid = 1;
            snx_d24_conversions++;
            snx_d24_pixels += (u64)s->w * s->h;
        }
    }
    if (ok && s->bl) {
        VkBlMove m = rt_bl_move(s, pitch);
        vk_bl_barrier(cb, 1);
        ok = vk_bl_move(cb, &m, 1, out, out_at, scratch, packed_at);
        vk_bl_barrier(cb, 0);
    } else if (ok) {
        vk_copy_rows(cb, scratch, packed_at, pitch, out, out_at, s->w * 4, s->w * 4, s->h);
    }
    if (!ok) { snx_d24_failures++; return 0; }
    snx_d24_packed++;
    snx_d24_reused += cached;
    if (snx_perf_on && snx_d24_states < 8) {
        snx_d24_states++;
        LOG("SNX_D24_PACK_STATE_V1 {\"surface\":\"%llx\",\"frame\":%u,\"wgen\":%u,"
            "\"guest_format\":%u,\"w\":%u,\"h\":%u,\"block_linear\":%u,\"block_height\":%u}\n",
            (unsigned long long)s->gva, g_vk_present, s->wgen, s->fkey & 0xffff, s->w, s->h, s->bl, s->bh);
    }
    return 1;
}

void snx_d24_pack_report(u64 window) {
    LOG("SNX_D24_PACK_V1 {\"window\":%llu,\"enabled\":%d,\"packed\":%llu,\"pixels\":%llu,\"failures\":%llu,"
        "\"conversions\":%llu,\"reused\":%llu,\"stale_rejected\":%llu,\"partial_rejected\":%llu}\n",
        (unsigned long long)window, snx_d24_pack_on, (unsigned long long)snx_d24_packed,
        (unsigned long long)snx_d24_pixels, (unsigned long long)snx_d24_failures,
        (unsigned long long)snx_d24_conversions, (unsigned long long)snx_d24_reused,
        (unsigned long long)snx_d24_stale, (unsigned long long)snx_d24_partial);
    snx_d24_packed = snx_d24_pixels = snx_d24_failures = 0;
    snx_d24_conversions = snx_d24_reused = snx_d24_stale = snx_d24_partial = 0;
    snx_d24_states = 0;
}
