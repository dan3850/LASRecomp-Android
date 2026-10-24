/* SPDX-License-Identifier: MIT
 * Opt-in evidence, included once by render.c under vk_lock. No guest writes.
 * A private readback survives until normal frame retirement; no extra wait or
 * submit is introduced. Disk I/O and three pass breaks make this diagnostic
 * unsuitable for performance comparisons. OFF records no additional work.
 */
#include <stdio.h>

#define SNX_SHADOW_CAP 3u
#define SNX_SHADOW_BYTES (64ull << 20)
static const u32 snx_shadow_regs[] = {
    0x280, 0x281, 0x282, 0x283, 0x284, 0x285, 0x286,
    0x302, 0x303, 0x35f, 0x370, 0x371, 0x372, 0x3fe,
    0x3f8, 0x3f9, 0x3fa, 0x3fb, 0x3fc, 0x48a, 0x48b, 0x48c, 0x54e,
    0x4b3, 0x4ba, 0x4c3, 0x4eb, 0x55b, 0x56f, 0x61f,
    0x646, 0x647, 0x648, 0x64b, 0x64f
};
typedef struct {
    VkImage image; /* identity only; never dereferenced after recording */
    u64 vs, fs;
    u32 frame, wgen, predicated, words[sizeof snx_shadow_regs / sizeof *snx_shadow_regs];
} SnxShadowDraw;
static SnxShadowDraw snx_shadow_draws[16];
static unsigned snx_shadow_draw_next, snx_shadow_count;
static int snx_shadow_enabled, snx_shadow_pending;
static u64 snx_shadow_due;
static char snx_shadow_dir[768];

void snx_shadow_init(void) {
    const char* dir = getenv("SNX_SHADOW_CAPTURE_DIR");
    if (!dir || !*dir) return;
    if (*dir != '/' || strlen(dir) >= sizeof snx_shadow_dir) {
        WARN("SNX_SHADOW_CAPTURE_V1 {\"status\":\"invalid_directory\"}\n");
        return;
    }
    strcpy(snx_shadow_dir, dir); /* directory is prepared by the launcher */
    snx_shadow_enabled = 1;
    snx_shadow_due = plat_ns() + 15000000000ull;
    LOG("SNX_SHADOW_CAPTURE_V1 {\"status\":\"armed\",\"limit\":3,\"interval_s\":15,"
        "\"max_bytes\":%llu,\"extra_waits\":0}\n", (unsigned long long)SNX_SHADOW_BYTES);
}

/* Called only after the original draw commands and target-written bookkeeping.
 * Predication is recorded, not interpreted as proof that any pixel was drawn.
 */
static void snx_shadow_note(const Surf* zt, const VkSh* vs, const VkSh* fs, const u32* r, int predicated) {
    if (!snx_shadow_enabled || snx_shadow_count == SNX_SHADOW_CAP || !zt || !r[0x4ba]) return;
    unsigned i;
    for (i = 0; i < 16 && snx_shadow_draws[i].image != zt->img; i++) {}
    if (i == 16) i = snx_shadow_draw_next++ % 16;
    SnxShadowDraw* d = &snx_shadow_draws[i];
    *d = (SnxShadowDraw){.image = zt->img, .vs = vs ? vs->hash : 0, .fs = fs ? fs->hash : 0,
                        .frame = g_vk_present, .wgen = zt->wgen, .predicated = !!predicated};
    for (unsigned j = 0; j < sizeof snx_shadow_regs / sizeof *snx_shadow_regs; j++)
        d->words[j] = r[snx_shadow_regs[j]];
}

typedef struct {
    VkBuffer buffer;
    VmaAllocation allocation;
    const void* mapped;
    u64 bytes, shader, gva;
    u32 capture, frame, wgen, w, h, sw, sh, layers, format, stage, slot, tic[8], tsc[8];
    int have_draw;
    SnxShadowDraw draw;
    char prefix[832];
} SnxShadowCapture;

/* .json is the completion marker: an exporter accepts only a matching pair.
 * The raw file is a tightly packed Vulkan DEPTH-aspect copy, NOT the guest's
 * interleaved depth/stencil memory. Invalidate only after the frame's wait.
 */
static void snx_shadow_saved(void* arg) {
    SnxShadowCapture* c = arg;
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
            fprintf(f, "{\"schema\":\"SNX_SHADOW_DEPTH_V1\",\"capture\":%u,\"frame\":%u,"
                    "\"surface\":\"%llx\",\"wgen\":%u,\"width\":%u,\"height\":%u,"
                    "\"image_width\":%u,\"image_height\":%u,\"layers\":%u,\"mip\":0,"
                    "\"format\":%u,\"bytes\":%llu,\"byte_order\":\"little\","
                    "\"consumer\":{\"shader\":\"%016llx\",\"stage\":%u,\"slot\":%u,\"tic\":[",
                    c->capture, c->frame, (unsigned long long)c->gva, c->wgen, c->w, c->h,
                    c->sw, c->sh, c->layers, c->format, (unsigned long long)c->bytes,
                    (unsigned long long)c->shader, c->stage, c->slot);
            for (int i = 0; i < 8; i++) fprintf(f, "%s%u", i ? "," : "", c->tic[i]);
            fprintf(f, "],\"tsc\":[");
            for (int i = 0; i < 8; i++) fprintf(f, "%s%u", i ? "," : "", c->tsc[i]);
            fprintf(f, "]},\"last_recorded_depth_draw\":{\"same_generation\":%d,\"frame\":%u,"
                    "\"vs\":\"%016llx\",\"fs\":\"%016llx\",\"predicated\":%u,\"registers\":{",
                    c->have_draw, c->draw.frame, (unsigned long long)c->draw.vs,
                    (unsigned long long)c->draw.fs, c->draw.predicated);
            if (c->have_draw)
                for (unsigned j = 0; j < sizeof snx_shadow_regs / sizeof *snx_shadow_regs; j++)
                    fprintf(f, "%s\"%03x\":\"%08x\"", j ? "," : "", snx_shadow_regs[j], c->draw.words[j]);
            fprintf(f, "}}}\n");
            ok = !ferror(f);
            if (fclose(f)) ok = 0;
        } else ok = 0;
        if (ok) ok = !rename(tmp, meta);
        if (!ok) remove(tmp);
    }
    LOG("SNX_SHADOW_CAPTURE_V1 {\"status\":\"%s\",\"capture\":%u,\"frame\":%u,"
        "\"layers\":%u,\"bytes\":%llu}\n", ok ? "saved" : "save_failed", c->capture,
        c->frame, c->layers, (unsigned long long)c->bytes);
    vmaDestroyBuffer(g_vk.vma, c->buffer, c->allocation);
    snx_shadow_pending = 0;
    free(c);
}

static void snx_shadow_capture(const VkSh* shader, int stage, int slot, Surf* t, const u32* tic, const u32* tsc) {
    if (!snx_shadow_enabled || snx_shadow_pending || snx_shadow_count == SNX_SHADOW_CAP ||
        plat_ns() < snx_shadow_due) return;
    /* Bound only the diagnostic. Never fail or skip the game's draw. All
     * image types here were created with TRANSFER_SRC and one sample. */
    u32 bpp = t->f.vk == VK_FORMAT_D16_UNORM || t->f.vk == VK_FORMAT_D16_UNORM_S8_UINT ? 2
              : t->f.vk == VK_FORMAT_D24_UNORM_S8_UINT || t->f.vk == VK_FORMAT_X8_D24_UNORM_PACK32 ||
                t->f.vk == VK_FORMAT_D32_SFLOAT || t->f.vk == VK_FORMAT_D32_SFLOAT_S8_UINT ? 4 : 0;
    /* surf_create leaves depth3d=0 for 2D render targets; texture-created
     * 2D images use 1. Both have an image copy extent depth of one. */
    if (!bpp || !t->sw || !t->sh || !t->layers || t->depth3d > 1 || t->levels != 1 ||
        t->layout == VK_IMAGE_LAYOUT_UNDEFINED || t->sw > 8192 || t->sh > 8192 || t->layers > 16) return;
    u64 bytes = (u64)t->sw * t->sh * t->layers * bpp;
    if (bytes > SNX_SHADOW_BYTES || bytes > g_vk.alloc_cap) {
        WARN_LIMIT(1, "SNX_SHADOW_CAPTURE_V1 {\"status\":\"size_refused\",\"bytes\":%llu}\n",
                   (unsigned long long)bytes);
        return;
    }
    snx_shadow_due = plat_ns() + 15000000000ull; /* allocation failures cannot retry every draw */
    SnxShadowCapture* c = calloc(1, sizeof *c);
    if (!c) return;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
                            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VmaAllocationCreateInfo ai = {.flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT |
                                        VMA_ALLOCATION_CREATE_MAPPED_BIT, .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST};
    VmaAllocationInfo info;
    if (!VK_OK(vmaCreateBuffer(g_vk.vma, &bi, &ai, &c->buffer, &c->allocation, &info))) { free(c); return; }
    if (!info.pMappedData) { vmaDestroyBuffer(g_vk.vma, c->buffer, c->allocation); free(c); return; }
    c->mapped = info.pMappedData; c->bytes = bytes; c->shader = shader->hash; c->stage = (u32)stage;
    c->slot = (u32)slot; c->gva = t->gva; c->wgen = t->wgen; c->frame = g_vk_present;
    c->w = t->w; c->h = t->h; c->sw = t->sw; c->sh = t->sh; c->layers = t->layers; c->format = (u32)t->f.vk;
    c->capture = ++snx_shadow_count;
    memcpy(c->tic, tic, sizeof c->tic); memcpy(c->tsc, tsc, sizeof c->tsc);
    for (unsigned i = 0; i < 16; i++)
        if (snx_shadow_draws[i].image == t->img && snx_shadow_draws[i].wgen == t->wgen &&
            snx_shadow_draws[i].frame == t->drawn_at) {
            c->draw = snx_shadow_draws[i]; c->have_draw = 1; break;
        }
    snprintf(c->prefix, sizeof c->prefix, "%s/shadow-%u", snx_shadow_dir, c->capture);
    /* Save/restore the exact old image use. The original sample transition
     * still runs afterwards, including every dependency it previously had. */
    VkImageLayout old = t->layout;
    VkPipelineStageFlags2 old_stage = t->stage;
    VkAccessFlags2 old_access = t->access;
    vk_render_end();
    VkCommandBuffer cb = vk_cmd();
    vk_surf_use(cb, t, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
    VkBufferImageCopy copy = {.imageSubresource = {VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, t->layers},
                             .imageExtent = {t->sw, t->sh, 1}};
    rec_CmdCopyImageToBuffer(cb, t->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, c->buffer, 1, &copy);
    VkMemoryBarrier2 mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
                          .srcStageMask = VK_PIPELINE_STAGE_2_COPY_BIT, .srcAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT,
                          .dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT, .dstAccessMask = VK_ACCESS_2_HOST_READ_BIT};
    VkDependencyInfo di = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .memoryBarrierCount = 1, .pMemoryBarriers = &mb};
    rec_CmdPipelineBarrier2(cb, &di);
    vk_surf_use(cb, t, old, old_stage, old_access);
    snx_shadow_pending = 1;
    snx_shadow_due = plat_ns() + 15000000000ull;
    vk_defer_call(snx_shadow_saved, c); /* callback owns c and its buffer */
    LOG("SNX_SHADOW_CAPTURE_V1 {\"status\":\"queued\",\"capture\":%u,\"frame\":%u}\n", c->capture, c->frame);
}
