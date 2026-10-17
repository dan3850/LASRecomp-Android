// Native Android: maintain the last CPU-authored version of each texture
// subresource while its real image stays resident on the GPU. Changed rows
// are staged as compact rectangles; the image is NEVER recreated for a
// content update. Existing queue ordering/full barriers remain unchanged.
//
// This is intentionally separate from GPU-written render targets: those
// require an image/resource ownership graph, not a CPU shadow shortcut.
// CPU-written glyph/video/patched textures may still update within a frame.
#include "texture_native.h"
#include "texture_regions.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define MAX_RUNS 32
#define SHADOW_BUDGET (64ull << 20)
#define MAX_SUBRESOURCE (8ull << 20)

typedef struct NativeTexLevel {
    struct NativeTexLevel *next;
    uint32_t mip, layer, w, h, bpp;
    size_t bytes;
    uint8_t *shadow;
} NativeTexLevel;

struct NativeTexResident {
    NativeTexLevel *levels;
};

static size_t total_shadow;
static uint64_t stat_full, stat_partial, stat_unchanged, stat_fallback;
static uint64_t stat_gpu_bytes, stat_avoided_bytes, stat_cpu_scanned;
static int native_on = -1;

bool vk_native_texture_enabled(void) {
    if (native_on < 0) {
        const char *e = getenv("LARECOMP_VK_NATIVE_TEXTURES");
#ifdef __ANDROID__
        native_on = !e || atoi(e) != 0;
#else
        native_on = e && atoi(e) != 0;
#endif
        LOG("[vk-texture-native] %s budget=64 MiB per-subresource=8 MiB "
            "LARECOMP_VK_NATIVE_TEXTURES=%s\n",
            native_on ? "enabled" : "disabled", e ? e : "unset");
    }
    return native_on != 0;
}

void vk_native_texture_discard(TexBackend *b) {
    if (!b || !b->native_tex) return;
    NativeTexLevel *p = b->native_tex->levels;
    while (p) {
        NativeTexLevel *next = p->next;
        total_shadow -= p->bytes;
        free(p->shadow);
        free(p);
        p = next;
    }
    free(b->native_tex);
    b->native_tex = NULL;
}

static NativeTexLevel *find_level(TexBackend *b, uint32_t mip, uint32_t layer) {
    if (!b->native_tex) return NULL;
    for (NativeTexLevel *p = b->native_tex->levels; p; p = p->next)
        if (p->mip == mip && p->layer == layer) return p;
    return NULL;
}

// Set shadow AFTER queueing the upload; upload staging gets a separate copy
// that remains valid until the submission's timeline value completes.
bool vk_native_texture_upload(TexBackend *b, uint32_t mip, uint32_t layer,
                             uint32_t w, uint32_t h, uint32_t bpp,
                             const uint8_t *pixels, size_t pitch) {
    if (!vk_native_texture_enabled() || !b || !pixels || b->gpu_owned ||
        b->aspect != VK_IMAGE_ASPECT_COLOR_BIT || b->depth != 1 ||
        b->samples != 1 || !b->image || mip >= b->levels || layer >= b->layers ||
        !w || !h || (bpp != 1 && bpp != 2 && bpp != 4 && bpp != 8 && bpp != 16)) return false;

    uint32_t max_w = b->width >> mip, max_h = b->height >> mip;
    if (!max_w) max_w = 1;
    if (!max_h) max_h = 1;
    if (w > max_w || h > max_h || (size_t)w > SIZE_MAX / bpp) return false;

    size_t row = (size_t)w * bpp;
    if (pitch < row || h > SIZE_MAX / row) return false;
    size_t size = row * h;
    if (size > MAX_SUBRESOURCE) { ++stat_fallback; return false; }

    NativeTexLevel *p = find_level(b, mip, layer);
    bool same_shape = p && p->w == w && p->h == h && p->bpp == bpp;
    NativeTexRows runs[MAX_RUNS];
    size_t dirty = size, count = SIZE_MAX;
    if (same_shape) {
        count = native_tex_dirty_rows(p->shadow, pixels, row, pitch, h,
                                      runs, MAX_RUNS, &dirty);
        stat_cpu_scanned += size;
        if (!count) { ++stat_unchanged; stat_avoided_bytes += size; return true; }
    }

    // No more than 32 independent copies. If >75% of the rows changed,
    // send one full image region instead of wasting driver work.
    bool full = !same_shape || count == SIZE_MAX || dirty > size * 3 / 4;
    if (full) { runs[0] = (NativeTexRows){0, h}; count = 1; dirty = size; }
    if (!count) return true;

    // Allocate a CPU shadow, bounded independently of Vulkan memory.
    // On pressure, fall back to the old full-image upload, never reuse a
    // stale version to claim a future cache hit.
    if (!same_shape) {
        size_t released = p ? p->bytes : 0;
        if (total_shadow - released + size > SHADOW_BUDGET) {
            ++stat_fallback;
            vk_native_texture_discard(b);
            return false;
        }
        uint8_t *memory = malloc(size);
        if (!memory) { ++stat_fallback; vk_native_texture_discard(b); return false; }
        if (!b->native_tex) {
            b->native_tex = calloc(1, sizeof *b->native_tex);
            if (!b->native_tex) { free(memory); ++stat_fallback; return false; }
        }
        if (!p) {
            p = calloc(1, sizeof *p);
            if (!p) { free(memory); ++stat_fallback; return false; }
            p->next = b->native_tex->levels;
            b->native_tex->levels = p;
        } else {
            total_shadow -= p->bytes;
            free(p->shadow);
        }
        p->shadow = memory;
        p->bytes = size;
        p->mip = mip; p->layer = layer; p->w = w; p->h = h; p->bpp = bpp;
        total_shadow += size;
    }

    // Each run starts at a four-byte aligned Vulkan buffer offset. The
    // Vulkan row length is tightly packed; source pitch is CPU-only.
    size_t offsets[MAX_RUNS];
    size_t staged = 0;
    for (size_t i = 0; i < count; ++i) {
        size_t align = bpp > 4 ? bpp : 4;
        staged = (staged + align - 1) & ~(align - 1);
        offsets[i] = staged;
        size_t region_size = (size_t)runs[i].count * row;
        if (region_size > SIZE_MAX - staged) { ++stat_fallback; return false; }
        staged += region_size;
    }
    VkSpan upload = vk_transient(staged, 16);
    VkBufferImageCopy copies[MAX_RUNS];
    for (size_t i = 0; i < count; ++i) {
        size_t off = offsets[i];
        for (uint32_t y = runs[i].first; y < runs[i].first + runs[i].count; ++y) {
            memcpy((uint8_t *)upload.ptr + off, pixels + (size_t)y * pitch, row);
            off += row;
        }
        copies[i] = (VkBufferImageCopy){
            .bufferOffset = upload.off + offsets[i],
            .bufferRowLength = w,
            .bufferImageHeight = runs[i].count,
            .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, mip, layer, 1},
            .imageOffset = {0, (int32_t)runs[i].first, 0},
            .imageExtent = {w, runs[i].count, 1},
        };
    }

    vkCmdCopyBufferToImage(vk_upload_cmd(), upload.buf, b->image,
                           VK_IMAGE_LAYOUT_GENERAL, (uint32_t)count, copies);
    for (uint32_t y = 0; y < h; ++y)
        memcpy(p->shadow + (size_t)y * row, pixels + (size_t)y * pitch, row);

    stat_gpu_bytes += dirty;
    stat_avoided_bytes += size - dirty;
    if (full) ++stat_full;
    else ++stat_partial;
    return true;
}

void vk_native_texture_stats(char *dst, size_t capacity) {
    if (!capacity || !vk_native_texture_enabled()) return;
    snprintf(dst, capacity, " | texture-native full %llu partial %llu same %llu "
        "fallback %llu GPU-upload %.1fMB avoided %.1fMB CPU-scan %.1fMB shadow %.1fMB",
        (unsigned long long)stat_full, (unsigned long long)stat_partial,
        (unsigned long long)stat_unchanged, (unsigned long long)stat_fallback,
        (double)stat_gpu_bytes / 1048576.0,
        (double)stat_avoided_bytes / 1048576.0,
        (double)stat_cpu_scanned / 1048576.0,
        (double)total_shadow / 1048576.0);
    stat_full = stat_partial = stat_unchanged = stat_fallback = 0;
    stat_gpu_bytes = stat_avoided_bytes = stat_cpu_scanned = 0;
}
