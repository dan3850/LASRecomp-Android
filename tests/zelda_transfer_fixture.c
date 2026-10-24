/* Execute the actual patched transfer functions with byte-addressable GPU
 * buffers and an explicit deferred-completion queue. No Android FPS claim.
 */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nx/gpu/gpu.h"

typedef struct TestBuffer { u8* data; u64 size, charge, id; } TestBuffer;
typedef TestBuffer* VkBuffer;
typedef TestBuffer* VmaAllocation;
typedef int VkCommandBuffer;
typedef int VkResult;
typedef struct { int sType; u64 size; unsigned usage; int sharingMode; } VkBufferCreateInfo;
typedef struct { int usage; } VmaAllocationCreateInfo;
typedef struct { u64 size; } VmaAllocationInfo;
typedef struct { u64 srcOffset, dstOffset, size; } VkBufferCopy;
enum { VK_SUCCESS, VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, VK_SHARING_MODE_EXCLUSIVE,
       VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE };
#define VK_BUFFER_USAGE_STORAGE_BUFFER_BIT 1
#define VK_BUFFER_USAGE_TRANSFER_SRC_BIT 2
#define VK_BUFFER_USAGE_TRANSFER_DST_BIT 4
#define VK_NULL_HANDLE NULL
#define VK_OK(x) ((x) == VK_SUCCESS)
#define LOG(...) printf(__VA_ARGS__)
#define LOG_LIMIT(n, ...) ((void)(n))
static struct { int vma; u64 alloc_cap; } g_vk = {0, 64ull << 20};
#include "resource_actual.inc"
#include "transfer.h"
static u64 frame, next_id, made, destroyed, charge, copies, barriers, scratch_calls, reads, stage_bytes;
static int fail_next, fail_stage, fail_heap, hole, overlay;
static u8 guest[4u << 20];
static TestBuffer* stages[4096];
static unsigned nstage;
static struct { void (*fn)(void*); void* arg; } deferred[4096];
static unsigned ndeferred;
static void vk_lock(void) {}
static void vk_unlock(void) {}
static u64 vk_frame_id(void) { return frame; }
static int vmaCreateBuffer(int allocator, const VkBufferCreateInfo* bi, const VmaAllocationCreateInfo* ai,
                           VkBuffer* b, VmaAllocation* m, void* info) {
    (void)allocator; (void)ai; (void)info;
    if (fail_next) { fail_next--; return -1; }
    if (fail_heap) return -1;
    TestBuffer* v = calloc(1, sizeof *v); assert(v);
    v->data = malloc(bi->size); assert(v->data);
    memset(v->data, 0xcd, bi->size);
    v->size = bi->size; v->charge = charge ? charge : bi->size; v->id = ++next_id;
    *b = *m = v; made++; return VK_SUCCESS;
}
static void vmaDestroyBuffer(int allocator, VkBuffer b, VmaAllocation m) {
    (void)allocator; assert(b == m); free(b->data); free(b); destroyed++;
}
static void vmaGetAllocationInfo(int allocator, VmaAllocation m, VmaAllocationInfo* info) {
    (void)allocator; info->size = m->charge;
}
static void vk_defer_call(void (*fn)(void*), void* arg) {
    assert(ndeferred < 4096); deferred[ndeferred++] = (typeof(deferred[0])){fn, arg};
}
static void deferred_destroy(void* p) { vmaDestroyBuffer(0, p, p); }
static void vk_defer_buffer(VkBuffer b, VmaAllocation m) { assert(b == m); vk_defer_call(deferred_destroy, b); }
static void complete_frame(void) {
    unsigned n = ndeferred; ndeferred = 0; frame++;
    for (unsigned i = 0; i < n; i++) deferred[i].fn(deferred[i].arg);
}
#include "transfer_impl.h"
#include "alloc_actual.inc"
#include "retain_actual.inc"
#include "release_actual.inc"
static void vk_own_res_unref(VkOwnRes* r) { res_release(r); }
static void rec_CmdCopyBuffer(VkCommandBuffer cb, VkBuffer src, VkBuffer dst, u32 n, const VkBufferCopy* r) {
    (void)cb; copies++;
    for (u32 i = 0; i < n; i++) {
        assert(r[i].srcOffset <= src->size && r[i].size <= src->size - r[i].srcOffset);
        assert(r[i].dstOffset <= dst->size && r[i].size <= dst->size - r[i].dstOffset);
        memmove(dst->data + r[i].dstOffset, src->data + r[i].srcOffset, r[i].size);
    }
}
#include "rows_baseline.inc"
#include "rows_actual.inc"
static VkBuffer buffer(u64 n) {
    VkBuffer b; VmaAllocation m; VkBufferCreateInfo bi = {.size = n}; VmaAllocationCreateInfo ai = {0};
    assert(!vmaCreateBuffer(0, &bi, &ai, &b, &m, NULL)); return b;
}
static u8* vk_stage(u64 n, u64 align, VkBuffer* b, u64* at) {
    (void)align; if (fail_stage) return NULL;
    assert(nstage < 4096); *b = stages[nstage++] = buffer(n); *at = 0;
    stage_bytes += n; return (*b)->data;
}
static u64 vk_stage_align(void) { return 16; }
static void vk_render_end(void) {}
static VkCommandBuffer vk_cmd(void) { return 1; }
static void vk_all_barrier(VkCommandBuffer cb) { (void)cb; barriers++; }
static VkBuffer vk_bl_scratch(u64 size, u64* cap) {
    assert(nstage < 4096); scratch_calls++; *cap = size; return stages[nstage++] = buffer(size);
}
static u64 gmmu_run(u64 a, u64 n, u64* cpu) {
    u64 run = 4096 - (a & 4095); if (run > n) run = n;
    if (a >= sizeof guest || (hole && (a >> 12) == 0x31)) return 0;
    *cpu = a; return run;
}
static void vk_guest_read(u64 a, u64 n, u8* dst, VkBuffer b, u64 at) {
    (void)b; (void)at; assert(a + n <= sizeof guest); reads += n; memcpy(dst, guest + a, n);
}
static void vk_rt_overlay(u64 a, u64 n, VkBuffer b, u64 at) {
    if (overlay && a <= 0x20040 && 0x20040 < a + n) b->data[at + 0x20040 - a] ^= 0x55;
}
static void vk_own_publish(u64 cpu, u64 n, VkOwnRes* r, u64 at) {
    assert(cpu + n <= sizeof guest && at + n <= r->size); memcpy(guest + cpu, r->buf->data + at, n);
}
void gpu_mem_written(u64 a, u64 n) { (void)a; (void)n; }
typedef struct { u32 w, h, bh, bd, oy, lines, z, slices, pitch; } VkBlMove;
static void vk_bl_range(const VkBlMove* m, u64* lo, u64* hi) { (void)m; *lo = *hi = 0; abort(); }
static int vk_bl_move(VkCommandBuffer cb, const VkBlMove* m, int inv, VkBuffer b, u64 at, VkBuffer dst, u64 off) {
    (void)cb; (void)m; (void)inv; (void)b; (void)at; (void)dst; (void)off; abort();
}
static int vk_tc_dma_remap(VkCommandBuffer cb, const GpuDmaOp* o, u32 lines, VkBuffer src, u64 at,
                           u32 pitch, VkBuffer dst, u64 off, u32 dp) {
    (void)cb; (void)o; (void)lines; (void)src; (void)at; (void)pitch; (void)dst; (void)off; (void)dp; abort();
}
#include "dma_helpers_actual.inc"
#define vk_copy_rows baseline_rows
#include "dma_baseline.inc"
#undef vk_copy_rows
#include "transfer_dma.h"
#include "dma_actual.inc"
static void reset_work(void) {
    complete_frame(); snx_transfer_reclaim(~0ull);
    for (unsigned i = 0; i < nstage; i++) vmaDestroyBuffer(0, stages[i], stages[i]);
    nstage = 0; copies = barriers = scratch_calls = reads = stage_bytes = 0;
    for (u64 i = 0; i < sizeof guest; i++) guest[i] = (u8)(i * 17 + (i >> 9));
}
static void test_pool(int on) {
    VkOwnRes* a = vk_own_res_new(4096); assert(a);
    VkBuffer original = a->buf; u64 identity = snx_transfer_identity(a);
    res_retain(a); res_release(a); assert(!ndeferred && !snx_transfer_n);
    res_release(a); assert(ndeferred == 1 && !snx_transfer_n);
    VkOwnRes* b = vk_own_res_new(4096); assert(b && b->buf != original);
    complete_frame();
    VkOwnRes* c = vk_own_res_new(4096); assert(c);
    if (on) assert(c->buf == original && snx_transfer_identity(c) != identity && snx_transfer_hits == 1);
    res_release(b); res_release(c); complete_frame();
    if (on) { assert(snx_transfer_n == 2); frame += 300; snx_transfer_frame(); assert(!snx_transfer_n); }
    for (int i = 0; i < 150; i++) { VkOwnRes* r = vk_own_res_new(256 + i); assert(r); res_release(r); }
    complete_frame();
    if (on) assert(snx_transfer_n == SNX_TRANSFER_POOL_N);
    snx_transfer_reclaim(~0ull);
    charge = 3u << 20;
    for (int i = 0; i < 150; i++) { VkOwnRes* r = vk_own_res_new(256 + i); assert(r); res_release(r); }
    complete_frame();
    assert(snx_transfer_n <= SNX_TRANSFER_POOL_N && snx_transfer_bytes <= SNX_TRANSFER_POOL_BYTES);
    if (on) {
        u64 was = snx_transfer_bytes; assert(was);
        fail_next = 1; VkOwnRes* r = vk_own_res_new(8192); assert(r && !snx_transfer_bytes); res_release(r);
        complete_frame(); assert(snx_transfer_reclaim(~0ull));
    }
    charge = 0; snx_transfer_reclaim(~0ull);
    assert(!snx_transfer_bytes && !snx_transfer_n);
    fail_heap = 1; assert(!vk_own_res_new(4096)); fail_heap = 0;
    assert(!vk_own_res_new(g_vk.alloc_cap + 1));
}
static void test_rows(int on) {
    VkBuffer src = buffer(8u << 20), expected = buffer(8u << 20), actual = buffer(8u << 20);
    for (u64 i = 0; i < src->size; i++) src->data[i] = (u8)(i * 31 + (i >> 8));
    const u32 counts[] = {0, 1, 63, 64, 65, 720, 1080};
    for (unsigned i = 0; i < sizeof counts / sizeof *counts; i++) for (int padded = 0; padded < 2; padded++) {
        memset(expected->data, 0xa7, expected->size); memset(actual->data, 0xa7, actual->size);
        u32 width = 5120, sp = width + (padded ? 64 : 0), dp = width + (padded ? 128 : 0);
        copies = 0; baseline_rows(1, src, 16, sp, expected, 32, dp, width, counts[i]); u64 old = copies;
        copies = 0; vk_copy_rows(1, src, 16, sp, actual, 32, dp, width, counts[i]);
        assert(!memcmp(expected->data, actual->data, actual->size));
        if (on && !padded && counts[i] > 64) assert(copies == 1 && old > copies);
        else assert(copies == old);
    }
    vmaDestroyBuffer(0, src, src); vmaDestroyBuffer(0, expected, expected); vmaDestroyBuffer(0, actual, actual);
}
static void test_dma(int on) {
    static u8 expected[sizeof guest], snap[65536];
    for (int i = 0; i < 65536; i++) snap[i] = (u8)(i ^ 0xa5);
    for (int padded = 0; padded < 2; padded++) for (int snapshot = 0; snapshot < 2; snapshot++)
    for (int overlap = 0; overlap < 2; overlap++) for (hole = 0; hole < 2; hole++) for (overlay = 0; overlay < 2; overlay++) {
        GpuDmaOp o = {.lines = 128, .line_in = 256, .line_out = 256,
            .src = {.addr = 0x20000, .pitch = 256 + (padded ? 32 : 0)},
            .dst = {.addr = overlap ? 0x21000 : 0x30000, .pitch = 256 + (padded ? 64 : 0)},
            .snap = snapshot ? snap : NULL};
        reset_work(); assert(baseline_dma(&o)); memcpy(expected, guest, sizeof guest);
        u64 old_reads = reads, old_stage = stage_bytes;
        reset_work(); assert(optimized_dma(&o)); assert(!memcmp(expected, guest, sizeof guest));
        if (on && !padded) {
            assert(!scratch_calls && copies == 1 && old_stage - stage_bytes == 32768);
            assert(old_reads - reads == 32768);
        }
    }
    GpuDmaOp o = {.lines = 1, .line_in = 64, .line_out = 64,
                 .src = {.addr = 0x20000, .pitch = 1024}, .dst = {.addr = 0x30000, .pitch = 2048}};
    reset_work(); assert(baseline_dma(&o)); memcpy(expected, guest, sizeof guest);
    reset_work(); assert(optimized_dma(&o)); assert(!memcmp(expected, guest, sizeof guest));
    if (on) {
        o.src.bl = 1; assert(snx_transfer_linear_dma(&o) == -1); o.src.bl = 0;
        o.dst.bl = 1; assert(snx_transfer_linear_dma(&o) == -1); o.dst.bl = 0;
        o.remap = 1; assert(snx_transfer_linear_dma(&o) == -1); o.remap = 0;
        o.fill = 1; assert(snx_transfer_linear_dma(&o) == -1); o.fill = 0;
        o.keep = 1; assert(snx_transfer_linear_dma(&o) == -1); o.keep = 0;
        o.line_in = 63; assert(snx_transfer_linear_dma(&o) == -1); o.line_in = 64;
        fail_stage = 1; assert(snx_transfer_linear_dma(&o) == 0); fail_stage = 0;
    }
    reset_work();
}
int main(void) {
    int on = snx_transfer_on();
    test_pool(on); test_rows(on); test_dma(on);
    snx_transfer_report(1);
    assert(!snx_transfer_hits && !snx_transfer_counts[SNX_XFER_LINEAR]);
    assert(made == destroyed);
    printf("TRANSFER_OK enabled=%d byte_exact=1 deferred_reuse=1 owner_identity=1 bounded_pool=1\n", on);
    return 0;
}
