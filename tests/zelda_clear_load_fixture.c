/* Actual render/recorder functions; Vulkan endpoints execute a delayed model. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef int32_t i32;
typedef uint64_t u64;
typedef u32 VkImageAspectFlags, VkRenderingFlags, VkImageLayout;
typedef u64 VkCommandBuffer, VkImage;
typedef struct { u32 width, height; } VkExtent2D;
typedef struct { i32 x, y; } VkOffset2D;
typedef struct { VkOffset2D offset; VkExtent2D extent; } VkRect2D;
typedef union { float float32[4]; u32 uint32[4]; i32 int32[4]; } VkClearColorValue;
typedef struct { float depth; u32 stencil; } VkClearDepthStencilValue;
typedef union { VkClearColorValue color; VkClearDepthStencilValue depthStencil; } VkClearValue;
typedef struct { u32 c[4], depth, stencil; } Pixel;
enum { IW = 16, IH = 12, IL = 3, PIXELS = IW * IH * IL };
typedef struct { u32 id; Pixel px[PIXELS]; } Image;
typedef struct { Image* image; int srgb; } View;
typedef View* VkImageView;
typedef struct {
    int sType; const void* pNext; VkImageView imageView; VkImageLayout imageLayout;
    u32 resolveMode; VkImageView resolveImageView; VkImageLayout resolveImageLayout;
    u32 loadOp, storeOp; VkClearValue clearValue;
} VkRenderingAttachmentInfo;
typedef struct {
    int sType; const void* pNext; VkRenderingFlags flags; VkRect2D renderArea;
    u32 layerCount, viewMask, colorAttachmentCount;
    const VkRenderingAttachmentInfo* pColorAttachments;
    const VkRenderingAttachmentInfo* pDepthAttachment;
    const VkRenderingAttachmentInfo* pStencilAttachment;
} VkRenderingInfo;
typedef struct { VkImageAspectFlags aspectMask; u32 colorAttachment; VkClearValue clearValue; } VkClearAttachment;
typedef struct { VkRect2D rect; u32 baseArrayLayer, layerCount; } VkClearRect;
typedef struct { int sType; u64 srcStageMask, srcAccessMask, dstStageMask, dstAccessMask; } VkMemoryBarrier2;
typedef struct {
    int sType; u32 dependencyFlags, memoryBarrierCount;
    const VkMemoryBarrier2* pMemoryBarriers;
} VkDependencyInfo;
#define VK_NULL_HANDLE NULL
#define VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO 1
#define VK_STRUCTURE_TYPE_RENDERING_INFO 2
#define VK_STRUCTURE_TYPE_MEMORY_BARRIER_2 3
#define VK_STRUCTURE_TYPE_DEPENDENCY_INFO 4
#define VK_ATTACHMENT_LOAD_OP_LOAD 0
#define VK_ATTACHMENT_LOAD_OP_CLEAR 1
#define VK_ATTACHMENT_STORE_OP_STORE 0
#define VK_ATTACHMENT_STORE_OP_NONE 1
#define VK_IMAGE_LAYOUT_UNDEFINED 0
#define VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL 1
#define VK_IMAGE_LAYOUT_DEPTH_STENCIL_READ_ONLY_OPTIMAL 2
#define VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL 3
#define VK_IMAGE_LAYOUT_ATTACHMENT_FEEDBACK_LOOP_OPTIMAL_EXT 4
#define VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT 1
#define VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT 2
#define VK_PIPELINE_STAGE_2_EARLY_FRAGMENT_TESTS_BIT 4
#define VK_PIPELINE_STAGE_2_LATE_FRAGMENT_TESTS_BIT 8
#define VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT 16
#define VK_ACCESS_2_COLOR_ATTACHMENT_READ_BIT 1
#define VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT 2
#define VK_ACCESS_2_SHADER_SAMPLED_READ_BIT 4
#define VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_READ_BIT 8
#define VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT 16
#define VK_DEPENDENCY_BY_REGION_BIT 1
#define VK_DEPENDENCY_FEEDBACK_LOOP_BIT_EXT 2
#define VK_SAMPLED_STAGES 18
#define VK_IMAGE_ASPECT_COLOR_BIT 1
#define VK_IMAGE_ASPECT_DEPTH_BIT 2
#define VK_IMAGE_ASPECT_STENCIL_BIT 4
#define LOG(...) printf(__VA_ARGS__)
#define LOG_LIMIT(n, ...) ((void)0)
typedef struct {
    u64 gva; u32 w, h, sw, sh, layers, depth3d;
    struct { int stencil, is_int; } f;
    int volume, pred_undefined;
    VkImage img; VkImageView att, att_linear;
    VkImageLayout layout;
    u32 wrote, drawn, full;
} Surf;
typedef struct { u32 r3d[0x1000]; u32 render_pred; } GpuChannel;
#include "scissor_actual.inc"
#include "clear_load.h"
#include "state_actual.inc"
static Rp base_rp, opt_rp;
static struct { int has_feedback, has_local_read; } g_vk;
static u64 g_vk_fb_restarts, g_vk_fb_barriers;
static Image images[9];
static View views[9][2];
static Surf surfaces[9], *bound[8], *depth;
static u32 nbound, record_pred;
static int fail_view;
typedef struct { u32 clear_commands, begins, ends, barriers, masked, uses, prof_begin, prof_end, queries, load_actions; } Work;
static Work work;
typedef void (*RecFn)(const void*);
typedef struct { RecFn fn; void* data; } Event;
static Event events[512];
static unsigned nevents, gpu_events;
static struct {
    VkRenderingAttachmentInfo c[8], z, s;
    u32 n, layers; VkRect2D area; int has_z, has_s, open;
} gpu;
static void enqueue(RecFn fn, const void* data, size_t size) {
    assert(nevents < sizeof events / sizeof *events);
    void* p = malloc(size); assert(p); memcpy(p, data, size); events[nevents++] = (Event){fn, p};
}
static void* rec_push(RecFn fn, u64 size) {
    assert(nevents < sizeof events / sizeof *events);
    void* p = calloc(1, size); assert(p); events[nevents++] = (Event){fn, p}; return p;
}
static void rec_commit(void) { }
static int rec_on(VkCommandBuffer cb) { return cb == 1; }
static void vk_rec_sync(void) { assert(!"unexpected chained rendering synchronization"); }
#define REC_AL(n) (((u64)(n) + 15) & ~15ull)
static void paint(View* view, VkRect2D rect, u32 layer, u32 layers, u32 aspects, const VkClearValue* value, u32 mask) {
    assert(view && rect.offset.x >= 0 && rect.offset.y >= 0);
    assert((u32)rect.offset.x + rect.extent.width <= IW && (u32)rect.offset.y + rect.extent.height <= IH);
    assert(layer + layers <= IL);
    for (u32 l = layer; l < layer + layers; l++)
        for (u32 y = (u32)rect.offset.y; y < (u32)rect.offset.y + rect.extent.height; y++)
            for (u32 x = (u32)rect.offset.x; x < (u32)rect.offset.x + rect.extent.width; x++) {
                Pixel* p = &view->image->px[(l * IH + y) * IW + x];
                if (aspects & VK_IMAGE_ASPECT_COLOR_BIT)
                    for (u32 c = 0; c < 4; c++) if (mask & (1u << c)) p->c[c] = value->color.uint32[c];
                if (aspects & VK_IMAGE_ASPECT_DEPTH_BIT) memcpy(&p->depth, &value->depthStencil.depth, 4);
                if (aspects & VK_IMAGE_ASPECT_STENCIL_BIT) p->stencil = value->depthStencil.stencil;
            }
}
static void vkCmdBeginRendering(VkCommandBuffer cb, const VkRenderingInfo* ri) {
    assert(cb == 1 && !gpu.open && ri->layerCount <= IL); gpu_events++; work.begins++;
    gpu.open = 1; gpu.n = ri->colorAttachmentCount; gpu.layers = ri->layerCount; gpu.area = ri->renderArea;
    memcpy(gpu.c, ri->pColorAttachments, gpu.n * sizeof *gpu.c);
    gpu.has_z = ri->pDepthAttachment != NULL; gpu.has_s = ri->pStencilAttachment != NULL;
    if (gpu.has_z) gpu.z = *ri->pDepthAttachment;
    if (gpu.has_s) gpu.s = *ri->pStencilAttachment;
    for (u32 i = 0; i < gpu.n; i++) if (gpu.c[i].imageView && gpu.c[i].loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) {
        work.load_actions++; paint(gpu.c[i].imageView, gpu.area, 0, gpu.layers, VK_IMAGE_ASPECT_COLOR_BIT, &gpu.c[i].clearValue, 15);
    }
    if (gpu.has_z && gpu.z.loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) {
        work.load_actions++; paint(gpu.z.imageView, gpu.area, 0, gpu.layers, VK_IMAGE_ASPECT_DEPTH_BIT, &gpu.z.clearValue, 0);
    }
    if (gpu.has_s && gpu.s.loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) {
        work.load_actions++; paint(gpu.s.imageView, gpu.area, 0, gpu.layers, VK_IMAGE_ASPECT_STENCIL_BIT, &gpu.s.clearValue, 0);
    }
}
#include "record_state_actual.inc"
#include "rendering_run_actual.inc"
#include "record_begin_actual.inc"
static void end_run(const void* p) { (void)p; assert(gpu.open); gpu.open = 0; gpu_events++; work.ends++; }
static void rec_CmdEndRendering(VkCommandBuffer cb) { assert(cb == 1); int dummy = 0; enqueue(end_run, &dummy, sizeof dummy); }
typedef struct { VkClearAttachment at[2]; VkClearRect rect; u32 n, pred, mask; } ClearEvent;
static void clear_run(const void* p) {
    const ClearEvent* x = p; assert(gpu.open); gpu_events++;
    if (x->pred == 2) return;
    for (u32 i = 0; i < x->n; i++) {
        const VkClearAttachment* a = &x->at[i];
        if (a->aspectMask & VK_IMAGE_ASPECT_COLOR_BIT) {
            assert(a->colorAttachment < gpu.n);
            paint(gpu.c[a->colorAttachment].imageView, x->rect.rect, x->rect.baseArrayLayer, x->rect.layerCount,
                  VK_IMAGE_ASPECT_COLOR_BIT, &a->clearValue, x->mask);
        }
        if (a->aspectMask & VK_IMAGE_ASPECT_DEPTH_BIT)
            paint(gpu.z.imageView, x->rect.rect, x->rect.baseArrayLayer, x->rect.layerCount, VK_IMAGE_ASPECT_DEPTH_BIT, &a->clearValue, 0);
        if (a->aspectMask & VK_IMAGE_ASPECT_STENCIL_BIT)
            paint(gpu.s.imageView, x->rect.rect, x->rect.baseArrayLayer, x->rect.layerCount, VK_IMAGE_ASPECT_STENCIL_BIT, &a->clearValue, 0);
    }
}
static void rec_CmdClearAttachments(VkCommandBuffer cb, u32 n, const VkClearAttachment* at, u32 nr, const VkClearRect* rect) {
    assert(cb == 1 && n <= 2 && nr == 1); work.clear_commands++;
    ClearEvent x = {.rect = *rect, .n = n, .pred = record_pred, .mask = 15}; memcpy(x.at, at, n * sizeof *at);
    enqueue(clear_run, &x, sizeof x);
}
static void pred_begin(VkCommandBuffer cb, u32 pred) { assert(cb == 1); record_pred = pred; }
static void pred_end(VkCommandBuffer cb, u32 pred) { assert(cb == 1 && record_pred == pred); record_pred = 0; }
static int clear_masked(u32 slot, u32 mask, const float* cc, VkRect2D rect, u32 layer, u32 pred) {
    ClearEvent x = {.rect = {rect, layer, 1}, .n = 1, .pred = pred, .mask = mask};
    x.at[0].aspectMask = VK_IMAGE_ASPECT_COLOR_BIT; x.at[0].colorAttachment = slot;
    memcpy(&x.at[0].clearValue.color, cc, 16); work.masked++; enqueue(clear_run, &x, sizeof x); return 1;
}
static void rec_CmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo* info) { assert(cb == 1 && info); work.barriers++; }
static VkCommandBuffer vk_cmd(void) { return 1; }
static void vk_query_pass_end(VkCommandBuffer cb) { assert(cb == 1); work.queries++; }
static void vk_gpuprof_pass_end(VkCommandBuffer cb) { assert(cb == 1); work.prof_end++; }
static void vk_gpuprof_pass_begin(VkCommandBuffer cb, Surf* color, Surf* z) { assert(cb == 1); (void)color; (void)z; work.prof_begin++; }
static void vk_surf_use(VkCommandBuffer cb, Surf* s, VkImageLayout layout, u64 stages, u64 access) {
    assert(cb == 1 && s && stages && access); s->layout = layout; work.uses++;
}
static VkImageView vk_rt_attachment(Surf* s, int srgb) { return fail_view ? NULL : srgb ? s->att : s->att_linear; }
static void vk_surf_wrote(Surf* s) { s->wrote++; }
static void vk_rt_drawn(Surf* s) { s->drawn++; }
static void vk_rt_drawn_full(Surf* s) { s->full++; }
static int trace_target(const Surf* s) { (void)s; return 0; }
static float vk_scf(float f) { return f; }
static void read_targets(GpuChannel* ch, Surf** rt, Surf** zt, u32* n) { (void)ch; memcpy(rt, bound, sizeof bound); *zt = depth; *n = nbound; }
#include "target_written_actual.inc"
#include "zt_written_actual.inc"
#define g_rp base_rp
#define vk_render_end base_end
#define render_begin base_begin
#define feedback_order base_feedback_order
#define feedback_done base_feedback_done
#define vk_render_clear base_clear
#include "end_actual.inc"
#include "begin_actual.inc"
#include "feedback_order_actual.inc"
#include "feedback_done_actual.inc"
#include "clear_actual.inc"
#undef g_rp
#undef vk_render_end
#undef render_begin
#undef feedback_order
#undef feedback_done
#undef vk_render_clear
#define g_rp opt_rp
#define vk_render_end opt_end
#define render_begin opt_begin
#define render_begin_load opt_begin_load
#define feedback_order opt_feedback_order
#define feedback_done opt_feedback_done
#define vk_render_clear opt_clear
#include "end_actual.inc"
#include "begin_load_changed.inc"
#include "begin_wrapper_changed.inc"
#include "feedback_order_actual.inc"
#include "feedback_done_actual.inc"
#include "clear_changed.inc"
#undef g_rp
#undef vk_render_end
#undef render_begin
#undef render_begin_load
#undef feedback_order
#undef feedback_done
#undef vk_render_clear

static volatile u64 stack_sink;
static void clobber_stack(void) { volatile u64 trash[1024]; for (u32 i = 0; i < 1024; i++) trash[i] = i * 0xfeed; stack_sink = trash[913]; }
static void init_world(void) {
    assert(nevents == 0); memset(&work, 0, sizeof work); memset(&gpu, 0, sizeof gpu);
    memset(&base_rp, 0, sizeof base_rp); memset(&opt_rp, 0, sizeof opt_rp); memset(&g_vk, 0, sizeof g_vk);
    memset(surfaces, 0, sizeof surfaces); memset(bound, 0, sizeof bound);
    fail_view = 0; record_pred = gpu_events = 0; g_vk_fb_restarts = g_vk_fb_barriers = 0;
    for (u32 i = 0; i < 9; i++) {
        images[i].id = i;
        for (u32 j = 0; j < PIXELS; j++) {
            images[i].px[j] = (Pixel){{i * 19 + j + 1, i + 22, j + 33, 444}, 0x3f000000, 0xa7};
        }
        views[i][0] = (View){&images[i], 0}; views[i][1] = (View){&images[i], 1};
        surfaces[i] = (Surf){.gva = 0x1000 * (i + 1), .w = 8, .h = 6, .sw = 8, .sh = 6, .layers = 1,
                            .depth3d = 1, .img = i + 1, .att = &views[i][1], .att_linear = &views[i][0]};
    }
    surfaces[8].f.stencil = 1; nbound = 1; bound[0] = &surfaces[0]; depth = NULL;
}
typedef struct { Pixel px[9][PIXELS]; u32 metadata[9][5]; Work work; u64 restarts, fb_barriers; } Result;
static void run_case(int optimized, int scene, Result* result) {
    init_world(); GpuChannel ch = {0}; u32 v = 15u << 2;
    const u32 values[4] = {0x3f000000, 0x3e800000, 0x3f400000, 0x3f800000};
    memcpy(ch.r3d + 0x360, values, 16); ch.r3d[0x364] = 0x3f800000; ch.r3d[0x368] = 0x12345;
    ch.r3d[0x56E] = 1; ch.r3d[0x487] = 1;
    switch (scene) {
    case 1: surfaces[0].f.is_int = 1; ch.r3d[0x360] = 185; ch.r3d[0x361] = 0xffffffff; break;
    case 2: depth = &surfaces[8]; v |= 3; break;
    case 3: nbound = 0; bound[0] = NULL; depth = &surfaces[8]; v = 3; break;
    case 4: nbound = 0; bound[0] = NULL; depth = &surfaces[8]; depth->f.stencil = 0; v = 1; break;
    case 5: ch.render_pred = 1; break;
    case 6: ch.render_pred = 2; depth = &surfaces[8]; v |= 3; break;
    case 7: ch.r3d[0x381] = 2 | (6 << 16); ch.r3d[0x382] = 1 | (5 << 16); break;
    case 8: ch.r3d[0x381] = 8 << 16; ch.r3d[0x382] = 6 << 16; break;
    case 9: v = 5 << 2; break;
    case 10: surfaces[0].layers = 2; v |= 1 << 10; break;
    case 12: depth = &surfaces[8]; v = 1; break;
    case 13: depth = &surfaces[8]; v = 2; break;
    case 14: nbound = 2; bound[1] = &surfaces[1]; surfaces[1].sw = 4; surfaces[1].sh = 3; break;
    case 15: nbound = 2; bound[1] = &surfaces[1]; surfaces[1].img = surfaces[0].img; surfaces[1].att = surfaces[0].att; break;
    case 16: depth = &surfaces[8]; depth->img = surfaces[0].img; depth->att = surfaces[0].att; v |= 3; break;
    case 17: surfaces[0].volume = 1; break;
    case 18: surfaces[0].depth3d = 2; break;
    case 19: v |= 5 << 6; break;
    case 20: nbound = 0; bound[0] = NULL; break;
    case 21: depth = &surfaces[8]; depth->f.stencil = 0; v |= 2; break;
    case 22: depth = &surfaces[8]; ch.r3d[0x364] = 0x7fc00001; ch.r3d[0x360] = 0x7f800000; v |= 3; break;
    case 23: ch.r3d[0x381] = 2 | (6 << 16); ch.r3d[0x382] = 1 | (5 << 16); ch.r3d[0x4EB] = 1; ch.r3d[0x3FE] = 6 << 16; break;
    case 26: depth = &surfaces[8]; depth->sw = 4; v |= 3; break;
    case 27: nbound = 2; bound[1] = &surfaces[0]; break;
    case 28: nbound = 2; bound[1] = bound[0]; bound[0] = NULL; v |= 1 << 6; break;
    case 29: case 30: case 31: g_vk.has_feedback = 1; surfaces[0].layout = VK_IMAGE_LAYOUT_ATTACHMENT_FEEDBACK_LOOP_OPTIMAL_EXT; g_vk.has_local_read = scene == 31; break;
    case 32: fail_view = 1; break;
    case 33: depth = &surfaces[8]; depth->layers = 2; surfaces[0].layers = 2; v |= 3; break;
    case 34: nbound = 2; bound[1] = &surfaces[1]; v |= 1 << 6; break;
    case 35: ch.r3d[0x56E] = 0; break;
    case 36: nbound = 0; bound[0] = NULL; depth = &surfaces[8]; v = 3; ch.r3d[0x364] = 0xbf800000; break;
    case 37: v |= 2047 << 10; break;
    case 38: depth = &surfaces[8]; v = 1; ch.render_pred = 2; break;
    case 39:
        nbound = 8; for (u32 i = 0; i < 8; i++) bound[i] = &surfaces[i];
        depth = &surfaces[8]; v |= (7 << 6) | 3; break;
    default: break;
    }
    if (scene == 7 || scene == 8 || scene == 23) { ch.r3d[0x43E] |= 0x100; ch.r3d[0x380] |= 1; }
    if (scene == 11 || scene == 30 || scene == 31) {
        assert(optimized ? opt_begin(bound, depth, nbound, 0, 1, 0) : base_begin(bound, depth, nbound, 0, 1, 0));
        if (scene >= 30) { if (optimized) opt_rp.fb_read = 1; else base_rp.fb_read = 1; }
    }
    if (optimized) opt_clear(&ch, v); else base_clear(&ch, v); clobber_stack();
    if (scene == 24 || scene == 25) {
        ch.r3d[0x360] = 0x3f600000;
        if (scene == 25) bound[0] = &surfaces[1];
        if (optimized) opt_clear(&ch, v); else base_clear(&ch, v); clobber_stack();
    }
    if (optimized) opt_end(); else base_end();
    assert(!gpu_events); /* no recorder callback has executed yet */
    for (unsigned i = 0; i < nevents; i++) { events[i].fn(events[i].data); free(events[i].data); }
    nevents = 0; assert(!gpu.open);
    memset(result, 0, sizeof *result);
    for (u32 i = 0; i < 9; i++) {
        memcpy(result->px[i], images[i].px, sizeof result->px[i]);
        const Surf* s = &surfaces[i];
        u32 m[5] = {s->layout, s->wrote, s->drawn, s->full, (u32)s->pred_undefined};
        memcpy(result->metadata[i], m, sizeof m);
    }
    result->work = work; result->restarts = g_vk_fb_restarts; result->fb_barriers = g_vk_fb_barriers;
}
static int expected_folds(int scene) {
    switch (scene) {
    case 0: case 1: case 2: case 3: case 4: case 21: case 22: case 24:
    case 28: case 29: case 34: case 35: case 36: case 39: return 1;
    case 25: return 2;
    default: return 0;
    }
}
int main(void) {
    int on = snx_clear_load_on();
    Result a, b;
    for (int scene = 0; scene < 40; scene++) {
        run_case(0, scene, &a); run_case(1, scene, &b);
        if (memcmp(a.px, b.px, sizeof a.px) || memcmp(a.metadata, b.metadata, sizeof a.metadata)) {
            fprintf(stderr, "clear-load model mismatch scene=%d\n", scene); return 1;
        }
        assert(a.restarts == b.restarts && a.fb_barriers == b.fb_barriers);
        u32 folds = on ? (u32)expected_folds(scene) : 0;
        assert(a.work.clear_commands == b.work.clear_commands + folds);
        if (folds) assert(b.work.load_actions > a.work.load_actions);
        Work aw = a.work, bw = b.work; aw.clear_commands = bw.clear_commands = 0; aw.load_actions = bw.load_actions = 0;
        assert(!memcmp(&aw, &bw, sizeof aw)); /* no extra pass, lost mask draw, barrier or metadata event */
    }
    snx_clear_load_report(1);
    for (u32 i = 0; i < SNX_CL_COUNT; i++) assert(!snx_clear_counts[i]);
    puts("CLEAR_LOAD_OK pixel_model_equal=1 metadata_equal=1 delayed_recorder=1 cases=40");
    return 0;
}
