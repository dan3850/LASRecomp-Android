/* Actual pinned functions; only the Vulkan/memory backend is instrumented. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef u64 VkPipelineStageFlags2;
typedef u64 VkAccessFlags2;
typedef struct Buffer { u8* data; u64 size; int device, deferred; struct Buffer* next; } *VkBuffer;
typedef VkBuffer VmaAllocation;
typedef struct { int sType; u64 size, usage; int sharingMode; } VkBufferCreateInfo;
typedef struct { int usage; } VmaAllocationCreateInfo;
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
#define VBH (1u << 16)
#include "vb_actual.inc"
static Vb* g_vbh[VBH], *baseline_vbh[VBH];
static struct { Vb* head; Vb* tail; u32 n; u64 bytes; } g_own;
static struct { void* vma; } g_vk;
static u32 g_vk_epoch = 1, g_vk_present = 1;
static u64 submit = 1, gpu_generation, cs_adds, gfx_adds;
static u64 g_copy_stage, g_copy_owned, g_read_bound;
static int g_cs_any, g_gfx_any, gx_mode, cs_mode, mapped = 1, fail_stage, fail_alloc, fail_temp, move_submit;
static int ww = -1;
static u8 guest[1 << 19], gpu_data[1 << 19];
static u8* g_tmp;
static u64 g_tmp_cap;
static VkBuffer allocations, arena;
static u64 arena_at;
static unsigned stages, makes, copy_commands, pass_ends, barriers, hashes, reads, gpu_direct, compositions, compute_direct;
static u64 checked_bytes;
#include "uniform.h"

static VkBuffer buffer_new(u64 size, int device) {
    VkBuffer b = calloc(1, sizeof *b); assert(b);
    b->data = calloc(1, size); assert(b->data); b->size = size; b->device = device;
    b->next = allocations; allocations = b; return b;
}
static int vmaCreateBuffer(void* vma, const VkBufferCreateInfo* bi, const VmaAllocationCreateInfo* ai,
                           VkBuffer* b, VmaAllocation* m, void* info) {
    (void)vma; (void)ai; (void)info; makes++;
    if (fail_alloc) return -1;
    *b = *m = buffer_new(bi->size, 1); return VK_SUCCESS;
}
static void vmaDestroyBuffer(void* vma, VkBuffer b, VmaAllocation m) { (void)vma; assert(b == m); b->deferred = 1; }
static void vk_defer_buffer(VkBuffer b, VmaAllocation m) { assert(b == m && !b->deferred); b->deferred = 1; }
static int copy_stats_on(void) { return 1; }
static u64 vk_submit_number(void) { return submit; }
static u64 vk_stage_align(void) { return 256; }
static u8* vk_stage(u64 len, u64 align, VkBuffer* b, u64* off) {
    if (fail_stage) return NULL;
    stages++;
    u64 at = (arena_at + align - 1) & ~(align - 1);
    if (!arena || at + len > arena->size) { arena = buffer_new(1 << 20, 0); at = 0; }
    *b = arena; *off = at; arena_at = at + len; return arena->data + at;
}
static void vk_render_end(void) { pass_ends++; }
static int vk_cmd(void) { return 1; }
static void rec_CmdCopyBuffer(int cb, VkBuffer src, VkBuffer dst, u32 n, const VkBufferCopy* r) {
    assert(cb == 1); copy_commands++;
    for (u32 i = 0; i < n; i++) {
        assert(r[i].srcOffset + r[i].size <= src->size && r[i].dstOffset + r[i].size <= dst->size);
        memcpy(dst->data + r[i].dstOffset, src->data + r[i].srcOffset, r[i].size);
    }
}
static void copy_barrier(VkPipelineStageFlags2 a, VkAccessFlags2 b, VkPipelineStageFlags2 c, VkAccessFlags2 d) {
    (void)a; (void)b; (void)c; (void)d; barriers++;
}
static u64 vk_compute_adds(void) { return cs_adds; }
static u64 vk_buf_adds(void) { return gfx_adds; }
static u64 gpu_mem_generation(void) { return gpu_generation; }
static int gpu_mem_dirty_since(u64 since, u64 a, u64 n) { (void)a; (void)n; return since != gpu_generation; }
static u32 vk_ww_now(void) { return 1; }
static int vk_written_since(const void* p, u64 n, u32 since) { (void)p; (void)n; (void)since; return ww; }
static void vk_compute_mem_need(u64 a, u64 n) { (void)a; (void)n; }
static int vk_buf_pending(u64 a, u64 n) { (void)a; (void)n; return gx_mode != 0; }
static int gpu_source(u64 a, u64 n, VkBuffer* b, u64* off) {
    u8* p = vk_stage(n, 256, b, off); if (!p) return 0;
    assert(a + n <= sizeof gpu_data); memcpy(p, gpu_data + a, n); return 1;
}
static int gfx_gpu_src(u64 a, u64 n, VkBuffer* b, u64* off, int writable) {
    assert(!writable);
    if (gx_mode == 1) { gpu_direct++; return gpu_source(a, n, b, off); }
    return gx_mode;
}
static int gfx_composed(u64 a, u64 n, VkBuffer* b, u64* off) { compositions++; return gpu_source(a, n, b, off); }
static int vk_compute_gpu_src(u64 a, u64 n, VkBuffer* b, u64* off) {
    if (!cs_mode) return 0;
    compute_direct++; return gpu_source(a, n, b, off);
}
static u8* gmem_ptr(u64 a, u64 n) {
    reads++;
    if (move_submit) { move_submit = 0; submit++; }
    assert(a + n <= sizeof guest);
    return mapped ? guest + a : NULL;
}
static int gmem_read(u64 a, void* p, u64 n) { assert(a + n <= sizeof guest); memcpy(p, guest + a, n); return 0; }
static void copy_note(u64 a, u64 n) { (void)a; (void)n; }
static void* temporary_realloc(void* p, size_t n) { return fail_temp ? NULL : realloc(p, n); }
#define realloc temporary_realloc
#include "guest_bytes_actual.inc"
#undef realloc
#include "hash_actual.inc"
static u64 checked_hash(const void* p, u64 n) { hashes++; checked_bytes += n; return vk_hash(p, n); }
static u64 vk_sample_hash(u64 a, u64 n) { assert(a + n <= sizeof guest); return vk_hash(guest + a, n); }
#include "own_link_actual.inc"
#include "own_unlink_actual.inc"
#include "use_actual.inc"
#include "drop_own_actual.inc"
#include "make_own_actual.inc"
#include "copy_actual.inc"
#define vk_hash checked_hash
#define g_vbh baseline_vbh
#include "baseline_actual.inc"
#undef g_vbh
#include "optimized_actual.inc"
#undef vk_hash
#include "wrappers_actual.inc"
static int baseline_strict(u64 a, u64 n, VkBuffer* b, u64* off) { return baseline_get(a, n, b, off, 1); }
typedef struct { u64 cbind[5][18]; u32 cbind_size[5][18]; } GpuChannel;
#include "cb_baseline.inc"
#include "cb_actual.inc"

typedef struct { VkBuffer b; u64 off, n; u8* bytes; } Snapshot;
static Snapshot snaps[256];
static unsigned nsnaps;
static void check_old(void) {
    for (unsigned i = 0; i < nsnaps; i++)
        assert(!memcmp(snaps[i].b->data + snaps[i].off, snaps[i].bytes, snaps[i].n));
}
static void remember(VkBuffer b, u64 off, const u8* bytes, u64 n) {
    assert(b && off + n <= b->size && !memcmp(b->data + off, bytes, n)); check_old();
    assert(nsnaps < sizeof snaps / sizeof *snaps);
    Snapshot* s = &snaps[nsnaps++]; *s = (Snapshot){b, off, n, malloc(n)}; assert(s->bytes); memcpy(s->bytes, bytes, n);
}
static void reset_case(void) {
    check_old();
    for (unsigned i = 0; i < nsnaps; i++) free(snaps[i].bytes);
    nsnaps = 0;
    for (unsigned i = 0; i < VBH; i++) {
        Vb* e = g_vbh[i]; while (e) { Vb* next = e->next; free(e); e = next; } g_vbh[i] = NULL;
        e = baseline_vbh[i]; while (e) { Vb* next = e->next; free(e); e = next; } baseline_vbh[i] = NULL;
    }
    while (allocations) { VkBuffer next = allocations->next; free(allocations->data); free(allocations); allocations = next; }
    arena = NULL; arena_at = 0; memset(&g_own, 0, sizeof g_own);
    stages = makes = copy_commands = pass_ends = barriers = hashes = reads = 0;
    gpu_direct = compositions = compute_direct = 0; checked_bytes = 0;
    g_copy_stage = g_copy_owned = g_read_bound = 0;
    g_vk_epoch += 100; g_vk_present++; submit += 10; gpu_generation++;
    cs_adds++; gfx_adds++; gx_mode = cs_mode = g_cs_any = g_gfx_any = 0;
    fail_alloc = fail_stage = fail_temp = move_submit = 0; mapped = 1; ww = -1;
    for (size_t i = 0; i < sizeof guest; i++) { guest[i] = (u8)(i * 19 + 3); gpu_data[i] = (u8)(i * 7 + 45); }
}
static int get(int opt, u64 a, u64 n, VkBuffer* b, u64* off) {
    return opt ? vk_buf_get_uniform(a, n, b, off) : baseline_get(a, n, b, off, 1);
}
typedef struct { unsigned stages, copies, ends, makes; } Work;
static Work stable_case(int opt, u64 len) {
    reset_case(); VkBuffer b; u64 off;
    for (int i = 0; i < 5; i++) {
        assert(get(opt, 4096, len, &b, &off)); remember(b, off, guest + 4096, len);
        unsigned read_before = hashes; g_vk_epoch++; /* no guest write, still strict each epoch */
        assert(hashes == read_before);
    }
    assert(hashes == 5 && checked_bytes == len * 5);
    Work work = {stages, copy_commands, pass_ends, makes};
    reset_case(); return work;
}
static void check_equivalence(int opt) {
    for (u64 n = 16; n <= 65536; n *= 4) {
        reset_case(); VkBuffer b; u64 off;
        for (int i = 0; i < 14; i++) {
            g_vk_epoch++;
            if (i % 3 == 2) { guest[8192 + (i * 127) % n] ^= 0x81; gpu_generation++; }
            assert(get(opt, 8192, n, &b, &off)); remember(b, off, guest + 8192, n);
        }
        assert(hashes == 14 && checked_bytes == 14 * n);
    }
    reset_case(); VkBuffer b, first; u64 off, first_off;
    assert(get(opt, 4096, 4096, &b, &off)); first = b; first_off = off;
    g_vk_epoch++; submit++;
    assert(get(opt, 4096, 4096, &b, &off));
    assert(b != first || off != first_off); /* never reuse a stale submission's ring snapshot */
    g_vk_epoch++; move_submit = 1; unsigned before = stages;
    assert(get(opt, 4096, 4096, &b, &off)); assert(stages > before);
    reset_case(); mapped = 0;
    assert(get(opt, 8192, 8192, &b, &off)); remember(b, off, guest + 8192, 8192);
    guest[8193] ^= 0xFF; gpu_generation++; g_vk_epoch++;
    assert(get(opt, 8192, 8192, &b, &off)); remember(b, off, guest + 8192, 8192);
    reset_case(); mapped = 0; fail_temp = 1; g_tmp_cap = 0;
    assert(!get(opt, 8192, 16384, &b, &off));
    fail_temp = 0; assert(get(opt, 8192, 16384, &b, &off)); remember(b, off, guest + 8192, 16384);
    reset_case(); fail_alloc = 1;
    for (int i = 0; i < 4; i++) { g_vk_epoch++; assert(get(opt, 4096, 4096, &b, &off)); remember(b, off, guest + 4096, 4096); }
    fail_stage = 1; guest[4098] ^= 0xF0; gpu_generation++; g_vk_epoch++;
    assert(!get(opt, 4096, 4096, &b, &off));
    fail_stage = 0; assert(get(opt, 4096, 4096, &b, &off)); remember(b, off, guest + 4096, 4096);
    reset_case(); assert(!get(opt, 4096, 0, &b, &off));
}
static void pending_cases(int opt) {
    for (int mode = 1; mode <= 3; mode++) {
        reset_case(); VkBuffer b; u64 off;
        assert(get(opt, 8192, 4096, &b, &off));
        gx_mode = mode <= 2 ? mode : 0; cs_mode = mode == 3;
        g_gfx_any = gx_mode != 0; g_cs_any = cs_mode; gfx_adds++; cs_adds++; g_vk_epoch++;
        unsigned old_reads = reads;
        assert(get(opt, 8192, 4096, &b, &off)); remember(b, off, gpu_data + 8192, 4096);
        assert(reads == old_reads);
        assert(mode == 1 ? gpu_direct == 1 : mode == 2 ? compositions == 1 : compute_direct == 1);
    }
    reset_case(); VkBuffer b; u64 off;
    /* A normal vertex consumer can promote a shared entry; uniforms retain it. */
    for (int i = 0; i < 3; i++) {
        g_vk_epoch++;
        assert(opt ? vk_buf_get(4096, 4096, &b, &off) : baseline_get(4096, 4096, &b, &off, 0));
    }
    assert(makes == 1); unsigned before = stages;
    g_vk_epoch++; assert(get(opt, 4096, 4096, &b, &off)); assert(stages == before);
    /* A CPU change must show immediately to a strict UBO, even after long stability. */
    for (int i = 0; i < 70; i++) { g_vk_epoch++; assert(get(opt, 4096, 4096, &b, &off)); }
    guest[4096 + 2048] ^= 0x55; g_vk_epoch++;
    assert(get(opt, 4096, 4096, &b, &off)); remember(b, off, guest + 4096, 4096);
    reset_case();
    /* Compute strict reads do not inherit the new graphics-only streaming policy. */
    for (int i = 0; i < 3; i++) { g_vk_epoch++; assert(vk_buf_get_strict(4096, 4096, &b, &off)); }
    assert(makes == 1);
}
static void binding_case(int opt) {
    reset_case(); GpuChannel ch = {0}; VkBuffer b; u64 off;
    ch.cbind[0][1] = 0x10000; ch.cbind_size[0][1] = 4096;
    int (*bind)(const GpuChannel*, int, int, u32, VkBuffer*, u64*) = opt ? cb_get : baseline_cb;
    for (int i = 0; i < 8; i++) {
        g_vk_epoch++; if (i % 2) { guest[0x10000 + i] ^= 0xA3; gpu_generation++; }
        assert(bind(&ch, 0, 1, 4096, &b, &off)); remember(b, off, guest + 0x10000, 4096);
    }
    gx_mode = 1; g_gfx_any = 1; gfx_adds++; g_vk_epoch++;
    assert(bind(&ch, 0, 1, 4096, &b, &off)); remember(b, off, gpu_data + 0x10000, 4096);
    assert(gpu_direct > 0);
}
int main(void) {
    int on = snx_uniform_on();
    for (u64 n = 16; n <= 65536; n *= 4) {
        Work a = stable_case(0, n), b = stable_case(1, n);
        assert(a.copies == 1 && a.ends == 1 && a.makes == 1);
        if (on) assert(b.copies == 0 && b.ends == 0 && b.makes == 0 && b.stages < a.stages);
        else assert(!memcmp(&a, &b, sizeof a));
    }
    Work a = stable_case(0, 65552), b = stable_case(1, 65552);
    assert(!memcmp(&a, &b, sizeof a)); /* >64 KiB retains the original policy */
    check_equivalence(0); check_equivalence(1);
    pending_cases(0); pending_cases(1);
    binding_case(0); binding_case(1);
    snx_uniform_report(1);
    for (unsigned i = 0; i < SNX_U_COUNT; i++) assert(!snx_uniform_counts[i]);
    reset_case(); free(g_tmp);
    puts("UNIFORM_OK byte_exact=1 strict_checks=1 old_draws_immutable=1 pending_gpu_preserved=1");
    return 0;
}
