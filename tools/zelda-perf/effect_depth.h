/* SPDX-License-Identifier: MIT
 * Pixel evidence under vk_lock. Independent of shadow capture. OFF does no
 * inspection. Three pairs maximum, one <=64 MiB buffer pending, 15s apart.
 * Existing retirement waits order CPU reads; no new wait/submit/guest write.
 */
#include <stdio.h>

#define SNX_EFFECT_BYTES (64ull << 20)
static int snx_effect_depth_on, snx_effect_depth_pending;
static unsigned snx_effect_depth_count;
static u64 snx_effect_depth_due;
static char snx_effect_depth_dir[768];

void snx_effect_depth_init(void) {
    const char* dir = getenv("SNX_EFFECT_DEPTH_DIR");
    if (!dir || !*dir) return;
    if (*dir != '/' || strlen(dir) >= sizeof snx_effect_depth_dir) {
        WARN("SNX_EFFECT_DEPTH_CAPTURE_V1 {\"status\":\"invalid_directory\"}\n");
        return;
    }
    strcpy(snx_effect_depth_dir, dir);
    snx_effect_depth_on = 1;
    snx_effect_depth_due = plat_ns() + 15000000000ull;
    LOG("SNX_EFFECT_DEPTH_CAPTURE_V1 {\"status\":\"armed\",\"limit\":3,\"interval_s\":15,"
        "\"max_bytes\":%llu,\"planes\":2,\"producer_relationship\":\"unproven\",\"extra_waits\":0}\n",
        (unsigned long long)SNX_EFFECT_BYTES);
}

typedef struct {
    VkBuffer buffer;
    VmaAllocation allocation;
    const void* mapped;
    u64 bytes, plane_bytes, shader, surface[2];
    u32 capture, frame, w, h, format, slot, wgen[2], guest_w[2], guest_h[2], tic[8], tsc[8];
    u32 clip, clip_control, viewport[6], depth_test, depth_write, depth_func;
    char prefix[832];
} SnxEffectDepthCapture;

static void snx_effect_depth_saved(void* arg) {
    SnxEffectDepthCapture* c = arg;
    char raw[864], meta[864], tmp[880];
    snprintf(raw, sizeof raw, "%s.depth", c->prefix);
    snprintf(meta, sizeof meta, "%s.json", c->prefix);
    snprintf(tmp, sizeof tmp, "%s.partial", raw);
    int ok = VK_OK(vmaInvalidateAllocation(g_vk.vma, c->allocation, 0, VK_WHOLE_SIZE));
    FILE* f = ok ? fopen(tmp, "wb") : NULL;
    ok = f && fwrite(c->mapped, 1, (size_t)c->bytes, f) == c->bytes;
    if (f && fclose(f)) ok = 0;
    if (ok) ok = !rename(tmp, raw);
    if (!ok) remove(tmp);
    if (ok) {
        snprintf(tmp, sizeof tmp, "%s.partial", meta);
        f = fopen(tmp, "wb");
        if (f) {
            fprintf(f, "{\"schema\":\"SNX_EFFECT_DEPTH_PAIR_V1\",\"capture\":%u,\"frame\":%u,"
                    "\"width\":%u,\"height\":%u,\"format\":%u,\"bytes\":%llu,\"byte_order\":\"little\","
                    "\"producer_relationship\":\"unproven\",\"planes\":[",
                    c->capture, c->frame, c->w, c->h, c->format, (unsigned long long)c->bytes);
            for (int i = 0; i < 2; i++)
                fprintf(f, "%s{\"role\":\"%s\",\"surface\":\"%llx\",\"wgen\":%u,\"guest_width\":%u,"
                        "\"guest_height\":%u,\"offset\":%llu,\"bytes\":%llu}", i ? "," : "",
                        i ? "sampled" : "attachment", (unsigned long long)c->surface[i], c->wgen[i],
                        c->guest_w[i], c->guest_h[i], (unsigned long long)(c->plane_bytes * i),
                        (unsigned long long)c->plane_bytes);
            fprintf(f, "],\"consumer\":{\"shader\":\"%016llx\",\"stage\":4,\"slot\":%u,\"tic\":[",
                    (unsigned long long)c->shader, c->slot);
            for (int i = 0; i < 8; i++) fprintf(f, "%s%u", i ? "," : "", c->tic[i]);
            fprintf(f, "],\"tsc\":[");
            for (int i = 0; i < 8; i++) fprintf(f, "%s%u", i ? "," : "", c->tsc[i]);
            fprintf(f, "]},\"draw_state\":{\"clip\":%u,\"clip_control\":%u,\"depth_test\":%u,"
                    "\"depth_write\":%u,\"depth_func\":%u,\"viewport_bits\":[", c->clip,
                    c->clip_control, c->depth_test, c->depth_write, c->depth_func);
            for (int i = 0; i < 6; i++) fprintf(f, "%s\"%08x\"", i ? "," : "", c->viewport[i]);
            fprintf(f, "]}}\n");
            ok = !ferror(f);
            if (fclose(f)) ok = 0;
        } else ok = 0;
        if (ok) ok = !rename(tmp, meta);
        if (!ok) remove(tmp);
    }
    LOG("SNX_EFFECT_DEPTH_CAPTURE_V1 {\"status\":\"%s\",\"capture\":%u,\"frame\":%u,\"bytes\":%llu}\n",
        ok ? "saved" : "save_failed", c->capture, c->frame, (unsigned long long)c->bytes);
    vmaDestroyBuffer(g_vk.vma, c->buffer, c->allocation);
    snx_effect_depth_pending = 0;
    free(c);
}

static int snx_effect_depth_image(const Surf* t) {
    return t && t->f.depth && t->img && t->sw && t->sh && t->sw <= 8192 && t->sh <= 8192 &&
           t->layers == 1 && t->depth3d <= 1 && t->levels == 1 && t->layout != VK_IMAGE_LAYOUT_UNDEFINED &&
           (t->f.vk == VK_FORMAT_D24_UNORM_S8_UINT || t->f.vk == VK_FORMAT_X8_D24_UNORM_PACK32 ||
            t->f.vk == VK_FORMAT_D32_SFLOAT || t->f.vk == VK_FORMAT_D32_SFLOAT_S8_UINT);
}

static void snx_effect_depth_capture(const VkSh* shader, int stage, int slot, Surf* attachment, Surf* sampled,
                                      const u32* tic, const u32* tsc, const u32* r) {
    if (!snx_effect_depth_on || snx_effect_depth_pending || snx_effect_depth_count == 3 ||
        plat_ns() < snx_effect_depth_due) return;
    /* Select only programs/slot observed reading scene depth in the supplied
     * post-correction logs. This never selects/replaces a gameplay shader. */
    if (stage != 4 || slot != 0 || !shader ||
        (shader->hash != 0x86d5a3f915a6795full && shader->hash != 0x2957c0d7d6264a3aull &&
         shader->hash != 0x7444fc6ce498b4bfull && shader->hash != 0x9f178ae97683fd4eull)) return;
    if (!snx_effect_depth_image(attachment) || !snx_effect_depth_image(sampled) ||
        attachment->img == sampled->img || attachment->sw != sampled->sw || attachment->sh != sampled->sh ||
        attachment->f.vk != sampled->f.vk) return;
    u64 plane = (u64)sampled->sw * sampled->sh * 4, bytes = plane * 2;
    if (bytes > SNX_EFFECT_BYTES || bytes > g_vk.alloc_cap) return;
    snx_effect_depth_due = plat_ns() + 15000000000ull; /* bounded retries after allocation failures */
    SnxEffectDepthCapture* c = calloc(1, sizeof *c);
    if (!c) return;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
                            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VmaAllocationCreateInfo ai = {.flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT |
                                        VMA_ALLOCATION_CREATE_MAPPED_BIT, .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST};
    VmaAllocationInfo info;
    if (!VK_OK(vmaCreateBuffer(g_vk.vma, &bi, &ai, &c->buffer, &c->allocation, &info))) { free(c); return; }
    if (!info.pMappedData) { vmaDestroyBuffer(g_vk.vma, c->buffer, c->allocation); free(c); return; }
    Surf* images[2] = {attachment, sampled};
    c->mapped = info.pMappedData; c->bytes = bytes; c->plane_bytes = plane;
    c->shader = shader->hash; c->slot = (u32)slot; c->frame = g_vk_present;
    c->w = sampled->sw; c->h = sampled->sh; c->format = (u32)sampled->f.vk;
    c->capture = ++snx_effect_depth_count;
    memcpy(c->tic, tic, sizeof c->tic); memcpy(c->tsc, tsc, sizeof c->tsc);
    memcpy(c->viewport, &r[0x280], sizeof c->viewport);
    c->clip = r[0x35f]; c->clip_control = r[0x64f]; c->depth_test = r[0x4b3];
    c->depth_write = r[0x4ba]; c->depth_func = r[0x4c3];
    snprintf(c->prefix, sizeof c->prefix, "%s/effect-%u", snx_effect_depth_dir, c->capture);
    vk_render_end();
    VkCommandBuffer cb = vk_cmd();
    for (int i = 0; i < 2; i++) {
        Surf* t = images[i];
        c->surface[i] = t->gva; c->wgen[i] = t->wgen; c->guest_w[i] = t->w; c->guest_h[i] = t->h;
        VkImageLayout old = t->layout;
        VkPipelineStageFlags2 old_stage = t->stage;
        VkAccessFlags2 old_access = t->access;
        vk_surf_use(cb, t, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_COPY_BIT,
                    VK_ACCESS_2_TRANSFER_READ_BIT);
        VkBufferImageCopy copy = {.bufferOffset = plane * i,
                                 .imageSubresource = {VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, 1},
                                 .imageExtent = {t->sw, t->sh, 1}};
        rec_CmdCopyImageToBuffer(cb, t->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, c->buffer, 1, &copy);
        vk_surf_use(cb, t, old, old_stage, old_access);
    }
    VkMemoryBarrier2 mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
                          .srcStageMask = VK_PIPELINE_STAGE_2_COPY_BIT, .srcAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT,
                          .dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT, .dstAccessMask = VK_ACCESS_2_HOST_READ_BIT};
    VkDependencyInfo di = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .memoryBarrierCount = 1, .pMemoryBarriers = &mb};
    rec_CmdPipelineBarrier2(cb, &di);
    snx_effect_depth_pending = 1;
    vk_defer_call(snx_effect_depth_saved, c);
    LOG("SNX_EFFECT_DEPTH_CAPTURE_V1 {\"status\":\"queued\",\"capture\":%u,\"frame\":%u}\n", c->capture, c->frame);
}
