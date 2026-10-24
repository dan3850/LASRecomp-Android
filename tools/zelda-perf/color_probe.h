/* SPDX-License-Identifier: MIT
 * Opt-in B10G11R11 color readback at three observed Zelda postprocess stages.
 * Uses the existing effect-capture switch. This measures output, not a repair.
 * All work is bounded to three frames, three small readbacks per frame.
 */
#define SNX_COLOR_PROBE_MAX_BYTES (16ull << 20)
typedef struct {
    VkBuffer buffer;
    VmaAllocation allocation;
    const u8* mapped;
    u64 bytes, shader, gva;
    u32 frame, width, height, stage, sample;
} SnxColorProbe;
static int snx_color_probe_on, snx_color_probe_pending;
static u32 snx_color_probe_frames, snx_color_probe_frame;
static u64 snx_color_probe_due;

void snx_color_probe_init(void) {
    if (!snx_effect_depth_on) return;
    snx_color_probe_on = 1;
    snx_color_probe_due = plat_ns() + 30000000000ull; /* wait for stable game startup */
    LOG("SNX_COLOR_PROBE_V1 {\"status\":\"armed\",\"frames\":3,\"stages\":3,\"format\":122,\"max_bytes\":%llu,\"extra_waits\":0}\n",
        (unsigned long long)SNX_COLOR_PROBE_MAX_BYTES);
}

static void snx_color_probe_saved(void* arg) {
    SnxColorProbe* p = arg;
    int ok = VK_OK(vmaInvalidateAllocation(g_vk.vma, p->allocation, 0, VK_WHOLE_SIZE));
    u64 zeros = 0, bright = 0, nonfinite = 0, pixels = (u64)p->width * p->height;
    u32 max_exponent = 0;
    if (ok) for (u64 i = 0; i < pixels; i++) {
        u32 bits;
        memcpy(&bits, p->mapped + i * 4, 4);
        u32 er = (bits >> 6) & 31, eg = (bits >> 17) & 31, eb = (bits >> 27) & 31;
        u32 e = er > eg ? er : eg;
        if (eb > e) e = eb;
        if (!bits) zeros++;
        if (e >= 19) bright++; /* at least one channel >= 16 (or nonfinite) */
        if (er == 31 || eg == 31 || eb == 31) nonfinite++;
        if (e > max_exponent) max_exponent = e;
    }
    LOG("SNX_COLOR_PROBE_V1 {\"status\":\"%s\",\"sample\":%u,\"frame\":%u,\"stage\":%u,"
        "\"shader\":\"%016llx\",\"surface\":\"%llx\",\"width\":%u,\"height\":%u,"
        "\"pixels\":%llu,\"zero_pixels\":%llu,\"bright_pixels\":%llu,"
        "\"nonfinite_pixels\":%llu,\"max_exponent\":%u}\n",
        ok ? "measured" : "invalidate_failed", p->sample, p->frame, p->stage,
        (unsigned long long)p->shader, (unsigned long long)p->gva, p->width, p->height,
        (unsigned long long)pixels, (unsigned long long)zeros, (unsigned long long)bright,
        (unsigned long long)nonfinite, max_exponent);
    vmaDestroyBuffer(g_vk.vma, p->buffer, p->allocation);
    snx_color_probe_pending = 0; /* only one outstanding GPU readback */
    free(p);
}

static void snx_color_probe_after_draw(const VkSh* fs, Surf* color, u32 writes) {
    /* The earlier probe broke up to three passes in one frame. Keep capture
     * entirely out of startup and serialize the readback with the already
     * active scene-depth capture. Never break a pass without a valid draw. */
    if (!snx_color_probe_on || snx_color_probe_pending || snx_effect_depth_pending ||
        !fs || !color || !(writes & 1) ||
        g_vk_present < 180 || snx_color_probe_frames >= 3 ||
        plat_ns() < snx_color_probe_due ||
        g_vk_present == snx_color_probe_frame) return;
    u32 stage = fs->hash == 0xe3d1871b2f5cda65ull ? 0 :
                fs->hash == 0xf889217164842d03ull ? 1 :
                fs->hash == 0x23e50e818480973cull ? 2 : 3;
    if (stage != snx_color_probe_frames) return;
    if (color->f.vk != VK_FORMAT_B10G11R11_UFLOAT_PACK32 || !color->img ||
        !color->sw || !color->sh || color->sw > 4096 || color->sh > 4096 ||
        color->layers != 1 || color->depth3d > 1 || color->levels != 1 ||
        color->layout == VK_IMAGE_LAYOUT_UNDEFINED) return;
    u64 bytes = (u64)color->sw * color->sh * 4;
    if (bytes > SNX_COLOR_PROBE_MAX_BYTES || bytes > g_vk.alloc_cap) return;
    snx_color_probe_due = plat_ns() + 1000000000ull; /* throttle failed allocations */
    SnxColorProbe* p = calloc(1, sizeof *p);
    if (!p) return;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
                             .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                             .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VmaAllocationCreateInfo ai = {.flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT |
                                         VMA_ALLOCATION_CREATE_MAPPED_BIT,
                                  .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST};
    VmaAllocationInfo info;
    if (!VK_OK(vmaCreateBuffer(g_vk.vma, &bi, &ai, &p->buffer, &p->allocation, &info))) {
        free(p); return;
    }
    if (!info.pMappedData) {
        vmaDestroyBuffer(g_vk.vma, p->buffer, p->allocation); free(p); return;
    }
    snx_color_probe_frame = g_vk_present;
    snx_color_probe_frames++;
    snx_color_probe_pending = 1;
    snx_color_probe_due = plat_ns() + 1000000ull; /* next stage: later presented frame */
    p->mapped = info.pMappedData; p->bytes = bytes; p->shader = fs->hash;
    p->gva = color->gva; p->frame = g_vk_present; p->width = color->sw;
    p->height = color->sh; p->stage = stage; p->sample = snx_color_probe_frames;
    VkImageLayout old = color->layout;
    VkPipelineStageFlags2 old_stage = color->stage;
    VkAccessFlags2 old_access = color->access;
    vk_render_end();
    VkCommandBuffer cb = vk_cmd();
    vk_surf_use(cb, color, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
    VkBufferImageCopy copy = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                              .imageExtent = {color->sw, color->sh, 1}};
    rec_CmdCopyImageToBuffer(cb, color->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                             p->buffer, 1, &copy);
    vk_surf_use(cb, color, old, old_stage, old_access);
    VkMemoryBarrier2 mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
                           .srcStageMask = VK_PIPELINE_STAGE_2_COPY_BIT,
                           .srcAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT,
                           .dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT,
                           .dstAccessMask = VK_ACCESS_2_HOST_READ_BIT};
    VkDependencyInfo di = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO,
                           .memoryBarrierCount = 1, .pMemoryBarriers = &mb};
    rec_CmdPipelineBarrier2(cb, &di);
    vk_defer_call(snx_color_probe_saved, p);
    LOG("SNX_COLOR_PROBE_V1 {\"status\":\"queued\",\"sample\":%u,\"frame\":%u,\"stage\":%u}\n",
        p->sample, p->frame, stage);
}
