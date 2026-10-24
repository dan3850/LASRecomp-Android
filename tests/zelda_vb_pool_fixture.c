/* Real make_own/drop_own/reclaim with ordered GPU commands + frame retirement. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int32_t i32;
typedef u64 VkPipelineStageFlags2, VkAccessFlags2;
typedef struct Buffer { u8* bytes; u64 size, charge, id; int destroyed; struct Buffer* next; } Buffer;
typedef Buffer* VkBuffer;
typedef Buffer* VmaAllocation;
typedef int VkResult;
typedef struct { int sType; u64 size; u32 usage, sharingMode; } VkBufferCreateInfo;
typedef struct { u32 usage; } VmaAllocationCreateInfo;
typedef struct { u64 size; } VmaAllocationInfo;
typedef struct { u64 srcOffset, dstOffset, size; } VkBufferCopy;
#define VK_NULL_HANDLE NULL
#define VK_SUCCESS 0
#define VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO 1
#define VK_BUFFER_USAGE_VERTEX_BUFFER_BIT 1
#define VK_BUFFER_USAGE_INDEX_BUFFER_BIT 2
#define VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT 4
#define VK_BUFFER_USAGE_STORAGE_BUFFER_BIT 8
#define VK_BUFFER_USAGE_UNIFORM_TEXEL_BUFFER_BIT 16
#define VK_BUFFER_USAGE_STORAGE_TEXEL_BUFFER_BIT 32
#define VK_BUFFER_USAGE_TRANSFER_DST_BIT 64
#define VK_SHARING_MODE_EXCLUSIVE 0
#define VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE 1
#define VK_PIPELINE_STAGE_2_COPY_BIT 1
#define VK_ACCESS_2_TRANSFER_WRITE_BIT 1
#define VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT 2
#define VK_ACCESS_2_MEMORY_READ_BIT 2
#define LOG(...) printf(__VA_ARGS__)
#include "vb_actual.inc"
static struct { Vb *head, *tail; u32 n; u64 bytes; } g_own;
static struct { void* vma; u64 alloc_cap; } g_vk = {0, 64ull << 20};
static u32 g_vk_present = 1;
static u64 frame, made, destroyed, next_id, fake_charge, g_copy_owned, commands, pass_ends, hash;
static int fail_alloc, fail_stage, fail_metadata;
static Buffer* allocations;
typedef struct { VkBuffer from, to; VkBufferCopy copy; u8* expected; } Work;
static Work work[512]; static unsigned nwork;
static struct { void (*fn)(void*); void* arg; } dead[512]; static unsigned ndead;
static Buffer* new_buffer(u64 size) {
    Buffer* b = calloc(1, sizeof *b); assert(b);
    b->bytes = malloc((size_t)size); assert(b->bytes); memset(b->bytes, 0xcd, (size_t)size);
    b->size = size; b->charge = fake_charge ? fake_charge : size; b->id = ++next_id;
    b->next = allocations; allocations = b; return b;
}
static int vmaCreateBuffer(void* a, const VkBufferCreateInfo* bi, const VmaAllocationCreateInfo* ai,
                           VkBuffer* b, VmaAllocation* m, void* info) {
    (void)a; assert(!info && bi->usage == 127 && ai->usage == VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE);
    if (fail_alloc) return -1;
    *b = *m = new_buffer(bi->size); made++; return 0;
}
static void vmaDestroyBuffer(void* a, VkBuffer b, VmaAllocation m) {
    (void)a; assert(b == m && !b->destroyed); b->destroyed = 1; destroyed++;
}
static void vmaGetAllocationInfo(void* a, VmaAllocation m, VmaAllocationInfo* info) { (void)a; info->size = m->charge; }
static u64 vk_frame_id(void) { return frame; }
static void vk_defer_call(void (*fn)(void*), void* arg) { assert(ndead < 512); dead[ndead++] = (typeof(dead[0])){fn, arg}; }
static void destroy_later(void* arg) { vmaDestroyBuffer(NULL, arg, arg); }
static void vk_defer_buffer(VkBuffer b, VmaAllocation m) { assert(b == m); vk_defer_call(destroy_later, b); }
static int copy_stats_on(void) { return 1; }
static void vk_defer_bytes(u64 n) { (void)n; }
static u64 snx_transfer_reclaim(u64 n) { (void)n; return 0; }
static void* metadata_alloc(size_t n) { return fail_metadata ? NULL : malloc(n); }
#define malloc metadata_alloc
#include "vb_pool.h"
#undef malloc
static void vk_render_end(void) { pass_ends++; }
static int vk_cmd(void) { return 1; }
static u64 vk_stage_align(void) { return 256; }
static u8* vk_stage(u64 n, u64 align, VkBuffer* b, u64* off) {
    assert(align == 256); if (fail_stage) return NULL;
    *b = new_buffer(n); *off = 0; return (*b)->bytes;
}
static void rec_CmdCopyBuffer(int cb, VkBuffer from, VkBuffer to, u32 n, const VkBufferCopy* r) {
    assert(cb == 1 && n == 1 && nwork < 512); commands++;
    work[nwork++] = (Work){from, to, *r, NULL};
}
static void copy_barrier(u64 a, u64 b, u64 c, u64 d) { assert(a == 1 && b == 1 && c == 2 && d == 2); }
#include "own_link_actual.inc"
#include "own_unlink_actual.inc"
#include "drop_own_actual.inc"
#include "make_own_actual.inc"
#include "reclaim_actual.inc"
#include "stats_actual.inc"
static void draw(VkBuffer b, const u8* expected, u64 n) {
    u8* copy = malloc(n); assert(copy); memcpy(copy, expected, n);
    work[nwork++] = (Work){.from = b, .copy = {0, 0, n}, .expected = copy};
}
static void complete_frame(void) {
    for (unsigned i = 0; i < nwork; i++) {
        Work* w = &work[i]; assert(!w->from->destroyed);
        if (w->expected) {
            assert(!memcmp(w->from->bytes, w->expected, w->copy.size));
            for (u64 j = 0; j < w->copy.size; j++) hash = hash * 33 + w->from->bytes[j];
            free(w->expected);
        } else {
            assert(!w->to->destroyed && w->copy.srcOffset + w->copy.size <= w->from->size &&
                   w->copy.dstOffset + w->copy.size <= w->to->size);
            memcpy(w->to->bytes + w->copy.dstOffset, w->from->bytes + w->copy.srcOffset, w->copy.size);
        }
    }
    nwork = 0; frame++; g_vk_present++;
    unsigned n = ndead; ndead = 0;
    for (unsigned i = 0; i < n; i++) dead[i].fn(dead[i].arg);
}
int main(void) {
    int enabled = snx_vb_pool_on(); u8 src[8192];
    for (unsigned scene = 0; scene < 50; scene++) {
        VkBuffer in_flight[3];
        for (unsigned k = 0; k < 3; k++) {
            u64 len = k == 2 ? 8192 : 4096; Vb e = {.len = len};
            memset(src, (int)(scene * 3 + k), sizeof src);
            assert(make_own(&e, src)); assert(e.own && e.off == 0);
            in_flight[k] = e.buf;
            for (unsigned j = 0; j < k; j++) assert(in_flight[j] != e.buf); /* pending resources never reused */
            draw(e.buf, src, len); memset(src, 0xee, sizeof src); drop_own(&e);
            assert(!e.own && !e.buf && !in_flight[k]->destroyed);
        }
        complete_frame();
    }
    printf("DRAW_BYTES %llu copies=%llu pass_ends=%llu made=%llu\n", (unsigned long long)hash,
           (unsigned long long)commands, (unsigned long long)pass_ends, (unsigned long long)made);
    assert(commands == 150 && pass_ends == 150 && !g_own.n && !g_own.bytes);
    assert(made == (enabled ? 3 : 150));
    u32 count; u64 bytes; vk_buf_stats(&count, &bytes); assert(count == snx_vb_idle_n && bytes == snx_vb_idle_bytes);
    snx_vb_pool_report(1);
    /* Staging failure must destroy the new/completed resource without queuing GPU work. */
    Vb e = {.len = 4096}; fail_stage = 1;
    assert(!make_own(&e, src) && !e.own && !nwork); fail_stage = 0;
    /* Allocation failure cannot recycle a pending buffer. Reclaim only idle memory. */
    e.len = 1234; fail_alloc = 1; assert(!make_own(&e, src)); fail_alloc = 0;
    complete_frame(); snx_vb_reclaim(~0ull); assert(!snx_vb_idle_n);
    /* Actual VMA charge, rather than requested bytes, bounds the idle pool. */
    fake_charge = SNX_VB_POOL_CAP + 1; e = (Vb){.len = 4096};
    assert(make_own(&e, src)); Buffer* oversized = e.buf; drop_own(&e); complete_frame();
    assert(oversized->destroyed && !snx_vb_idle_n); fake_charge = 0;
    /* Metadata allocation failure preserves the original deferred destroy path. */
    e = (Vb){.len = 4096}; assert(make_own(&e, src)); fail_metadata = 1;
    Buffer* no_meta = e.buf; drop_own(&e); assert(!no_meta->destroyed); fail_metadata = 0;
    complete_frame(); assert(no_meta->destroyed);
    if (enabled) {
        for (unsigned i = 0; i < 65; i++) {
            e = (Vb){.len = 16 + i}; assert(make_own(&e, src)); drop_own(&e);
        }
        complete_frame(); assert(snx_vb_idle_n == 64 && snx_vb_idle_bytes <= SNX_VB_POOL_CAP);
        assert(vk_buf_reclaim(0, 1) >= 1); /* idle pool participates in original memory pressure handling */
        frame += 300; snx_vb_frame(); assert(!snx_vb_idle_n);
        fake_charge = 20ull << 20;
        for (unsigned i = 0; i < 2; i++) { e = (Vb){.len = 4096 + i}; assert(make_own(&e, src)); drop_own(&e); }
        complete_frame(); assert(snx_vb_idle_n == 1 && snx_vb_idle_bytes == (20ull << 20)); fake_charge = 0;
    }
    snx_vb_reclaim(~0ull); assert(!snx_vb_idle_n && !ndead && made == destroyed);
    for (Buffer* b = allocations; b;) { Buffer* next = b->next; free(b->bytes); free(b); b = next; }
    puts("VB_POOL_OK retired_only=1 exact_bytes=1 bounded=1 failure_fallbacks=1");
    return 0;
}
