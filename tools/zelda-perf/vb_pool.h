/* SPDX-License-Identifier: MIT
 * Buffer-cache allocations only. VkOwnRes already has the transfer pool.
 * Reuse after the existing frame completion callback, exact sizes/usage only.
 * All calls, including retirement/reporting, hold the existing Vulkan lock.
 */
#include <stdio.h>
#define SNX_VB_POOL_N 64u
#define SNX_VB_POOL_CAP (32ull << 20)
typedef struct { VkBuffer buffer; VmaAllocation memory; u64 size, bytes, frame; } SnxVbIdle;
static SnxVbIdle snx_vb_idle[SNX_VB_POOL_N];
static unsigned snx_vb_idle_n;
static u64 snx_vb_idle_bytes;
enum { SNX_VB_REQUESTS, SNX_VB_HITS, SNX_VB_ALLOC_CALLS, SNX_VB_ALLOCATED,
       SNX_VB_ALLOC_FAILED, SNX_VB_RELEASES, SNX_VB_QUEUED, SNX_VB_RETURNED,
       SNX_VB_EVICTED, SNX_VB_STAGE_FAILED, SNX_VB_COUNT };
static u64 snx_vb_counts[SNX_VB_COUNT];
int snx_vb_pool_on(void) {
    static int mode = -1;
    if (mode < 0) {
        const char* e = getenv("SNX_VK_VB_POOL");
        mode = e && !strcmp(e, "1");
        LOG("SNX_VB_POOL_META_V1 {\"enabled\":%d,\"cap_bytes\":%llu,\"cap_entries\":64,"
            "\"exact_size\":1,\"fence_safe\":1,\"copies_unchanged\":1}\n",
            mode, (unsigned long long)SNX_VB_POOL_CAP);
    }
    return mode;
}
static void snx_vb_evict(unsigned i) {
    SnxVbIdle e = snx_vb_idle[i];
    snx_vb_idle_bytes -= e.bytes;
    snx_vb_idle[i] = snx_vb_idle[--snx_vb_idle_n];
    vmaDestroyBuffer(g_vk.vma, e.buffer, e.memory);
    snx_vb_counts[SNX_VB_EVICTED]++;
}
static u64 snx_vb_reclaim(u64 want) {
    u64 before = snx_vb_idle_bytes;
    while (snx_vb_idle_n && before - snx_vb_idle_bytes < want) {
        unsigned oldest = 0;
        for (unsigned i = 1; i < snx_vb_idle_n; i++)
            if (snx_vb_idle[i].frame < snx_vb_idle[oldest].frame) oldest = i;
        snx_vb_evict(oldest);
    }
    return before - snx_vb_idle_bytes;
}
static void snx_vb_frame(void) {
    u64 now = vk_frame_id();
    for (unsigned i = 0; i < snx_vb_idle_n;)
        if (now - snx_vb_idle[i].frame >= 300) snx_vb_evict(i);
        else i++;
}
static int snx_vb_allocate(const VkBufferCreateInfo* bi, const VmaAllocationCreateInfo* ai,
                           VkBuffer* buffer, VmaAllocation* memory) {
    snx_vb_counts[SNX_VB_REQUESTS]++;
    if (snx_vb_pool_on()) {
        snx_vb_frame();
        for (unsigned i = 0; i < snx_vb_idle_n; i++)
            if (snx_vb_idle[i].size == bi->size) {
                *buffer = snx_vb_idle[i].buffer; *memory = snx_vb_idle[i].memory;
                snx_vb_idle_bytes -= snx_vb_idle[i].bytes;
                snx_vb_idle[i] = snx_vb_idle[--snx_vb_idle_n];
                snx_vb_counts[SNX_VB_HITS]++;
                return 1;
            }
    }
    snx_vb_counts[SNX_VB_ALLOC_CALLS]++;
    VkResult result = vmaCreateBuffer(g_vk.vma, bi, ai, buffer, memory, NULL);
    if (result != VK_SUCCESS && snx_vb_pool_on() && snx_vb_reclaim(~0ull)) {
        snx_vb_counts[SNX_VB_ALLOC_CALLS]++;
        result = vmaCreateBuffer(g_vk.vma, bi, ai, buffer, memory, NULL);
    }
    snx_vb_counts[result == VK_SUCCESS ? SNX_VB_ALLOCATED : SNX_VB_ALLOC_FAILED]++;
    return result == VK_SUCCESS;
}
static void snx_vb_retired(void* arg) {
    SnxVbIdle e = *(SnxVbIdle*)arg;
    free(arg);
    VmaAllocationInfo info;
    vmaGetAllocationInfo(g_vk.vma, e.memory, &info);
    e.bytes = info.size; e.frame = vk_frame_id();
    if (!snx_vb_pool_on() || e.bytes > SNX_VB_POOL_CAP || e.size > g_vk.alloc_cap) {
        vmaDestroyBuffer(g_vk.vma, e.buffer, e.memory);
        return;
    }
    if (snx_vb_idle_n == SNX_VB_POOL_N) snx_vb_reclaim(snx_vb_idle[0].bytes);
    if (snx_vb_idle_bytes > SNX_VB_POOL_CAP - e.bytes)
        snx_vb_reclaim(snx_vb_idle_bytes - (SNX_VB_POOL_CAP - e.bytes));
    snx_vb_idle[snx_vb_idle_n++] = e; snx_vb_idle_bytes += e.bytes;
    snx_vb_counts[SNX_VB_RETURNED]++;
}
static void snx_vb_release(VkBuffer buffer, VmaAllocation memory, u64 size) {
    snx_vb_counts[SNX_VB_RELEASES]++;
    SnxVbIdle* e = snx_vb_pool_on() && size <= SNX_VB_POOL_CAP ? malloc(sizeof *e) : NULL;
    if (!e) { vk_defer_buffer(buffer, memory); return; }
    *e = (SnxVbIdle){.buffer = buffer, .memory = memory, .size = size};
    snx_vb_counts[SNX_VB_QUEUED]++;
    vk_defer_call(snx_vb_retired, e);
}
static void snx_vb_abandon(VkBuffer buffer, VmaAllocation memory) {
    /* Staging failed before any command referenced this completed/new buffer. */
    snx_vb_counts[SNX_VB_STAGE_FAILED]++;
    vmaDestroyBuffer(g_vk.vma, buffer, memory);
}
void snx_vb_pool_report(u64 window) {
    static const char* names[SNX_VB_COUNT] = {"requests", "pool_hits", "allocation_calls", "allocated", "allocation_failures",
        "release_requests", "queued_returns", "returned", "evicted", "staging_failures"};
    char line[1000];
    size_t n = (size_t)snprintf(line, sizeof line, "SNX_VB_POOL_V1 {\"window\":%llu,\"enabled\":%d",
                               (unsigned long long)window, snx_vb_pool_on());
    for (unsigned i = 0; i < SNX_VB_COUNT; i++)
        n += (size_t)snprintf(line + n, sizeof line - n, ",\"%s\":%llu", names[i], (unsigned long long)snx_vb_counts[i]);
    snprintf(line + n, sizeof line - n, ",\"pool_entries\":%u,\"pool_bytes\":%llu}",
             snx_vb_idle_n, (unsigned long long)snx_vb_idle_bytes);
    LOG("%s\n", line);
    memset(snx_vb_counts, 0, sizeof snx_vb_counts);
}
