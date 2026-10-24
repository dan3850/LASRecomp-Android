/* SPDX-License-Identifier: MIT
 * Included by owned.c. A result can be reused only after its final reference
 * is released AND the existing vk_defer_call frame fence has completed.
 * Reused storage is uninitialized, exactly like a new Vulkan buffer.
 */
#ifndef SNX_TRANSFER_IMPL_H
#define SNX_TRANSFER_IMPL_H
#define SNX_TRANSFER_POOL_N 128
#define SNX_TRANSFER_POOL_BYTES (64ull << 20)
static struct {
    VkOwnRes* r;
    u64 bytes, frame;
} snx_transfer_pool[SNX_TRANSFER_POOL_N];
static unsigned snx_transfer_n;
static u64 snx_transfer_bytes, snx_transfer_counts[SNX_XFER_N];
static u64 snx_transfer_hits, snx_transfer_misses, snx_transfer_evicted;
static u64 snx_transfer_generation;
int snx_transfer_on(void) {
    static int mode = -1;
    if (mode < 0) {
        const char* e = getenv("SNX_VK_TRANSFER_REUSE");
        mode = e && !strcmp(e, "1");
        LOG("SNX_TRANSFER_META_V1 {\"enabled\":%d,\"pool_cap_bytes\":%llu,\"fence_safe\":1}\n",
            mode, (unsigned long long)SNX_TRANSFER_POOL_BYTES);
    }
    return mode;
}
void snx_transfer_note(unsigned counter, u64 amount) {
    if (counter < SNX_XFER_N) snx_transfer_counts[counter] += amount;
}
static void snx_transfer_evict(unsigned i) {
    VkOwnRes* r = snx_transfer_pool[i].r;
    snx_transfer_bytes -= snx_transfer_pool[i].bytes;
    snx_transfer_pool[i] = snx_transfer_pool[--snx_transfer_n];
    vmaDestroyBuffer(g_vk.vma, r->buf, r->mem);
    free(r);
    snx_transfer_evicted++;
}
u64 snx_transfer_reclaim(u64 want) {
    u64 before = snx_transfer_bytes;
    while (snx_transfer_n && before - snx_transfer_bytes < want) {
        unsigned oldest = 0;
        for (unsigned i = 1; i < snx_transfer_n; i++)
            if (snx_transfer_pool[i].frame < snx_transfer_pool[oldest].frame) oldest = i;
        snx_transfer_evict(oldest);
    }
    return before - snx_transfer_bytes;
}
void snx_transfer_frame(void) {
    u64 now = vk_frame_id();
    for (unsigned i = 0; i < snx_transfer_n;)
        if (now - snx_transfer_pool[i].frame >= 300) snx_transfer_evict(i);
        else i++;
}
static VkOwnRes* snx_transfer_take(u64 size) {
    if (!snx_transfer_on()) return NULL;
    if (size > g_vk.alloc_cap) return NULL;
    snx_transfer_frame();
    for (unsigned i = 0; i < snx_transfer_n; i++) {
        VkOwnRes* r = snx_transfer_pool[i].r;
        if (r->size != size) continue; /* exact size, identical usage and layout */
        snx_transfer_bytes -= snx_transfer_pool[i].bytes;
        snx_transfer_pool[i] = snx_transfer_pool[--snx_transfer_n];
        r->refs = 1;
        r->generation = ++snx_transfer_generation;
        snx_transfer_hits++;
        return r;
    }
    snx_transfer_misses++;
    return NULL;
}
/* Resource addresses are reused too: a new result MUST have a new hash tag,
 * otherwise owner-based texture checks could mistake it for the old contents.
 * The original pointer identity is retained exactly when this option is OFF.
 */
static u64 snx_transfer_identity(void* res) {
    return snx_transfer_on() ? ((VkOwnRes*)res)->generation : (u64)(uintptr_t)res;
}
/* Invoked by dead_free after timeline_wait and land_through, never at unref. */
static void snx_transfer_retire(void* arg) {
    VkOwnRes* r = arg;
    VmaAllocationInfo info;
    vmaGetAllocationInfo(g_vk.vma, r->mem, &info);
    if (!snx_transfer_on() || info.size > SNX_TRANSFER_POOL_BYTES) {
        vmaDestroyBuffer(g_vk.vma, r->buf, r->mem);
        free(r);
        return;
    }
    if (snx_transfer_n == SNX_TRANSFER_POOL_N)
        snx_transfer_reclaim(snx_transfer_pool[0].bytes);
    if (snx_transfer_bytes > SNX_TRANSFER_POOL_BYTES - info.size)
        snx_transfer_reclaim(snx_transfer_bytes - (SNX_TRANSFER_POOL_BYTES - info.size));
    snx_transfer_pool[snx_transfer_n++] = (typeof(snx_transfer_pool[0])){r, info.size, vk_frame_id()};
    snx_transfer_bytes += info.size;
}
void snx_transfer_report(u64 window) {
    LOG("SNX_TRANSFER_V1 {\"window\":%llu,\"enabled\":%d,\"pool_hits\":%llu,\"pool_misses\":%llu,"
        "\"pool_evicted\":%llu,\"pool_entries\":%u,\"pool_bytes\":%llu,"
        "\"row_calls_before\":%llu,\"row_calls_after\":%llu,\"linear_dma\":%llu,"
        "\"linear_bytes\":%llu,\"dst_stage_bytes_avoided\":%llu}\n",
        (unsigned long long)window, snx_transfer_on(),
        (unsigned long long)snx_transfer_hits, (unsigned long long)snx_transfer_misses,
        (unsigned long long)snx_transfer_evicted, snx_transfer_n, (unsigned long long)snx_transfer_bytes,
        (unsigned long long)snx_transfer_counts[SNX_XFER_ROW_BEFORE],
        (unsigned long long)snx_transfer_counts[SNX_XFER_ROW_AFTER],
        (unsigned long long)snx_transfer_counts[SNX_XFER_LINEAR],
        (unsigned long long)snx_transfer_counts[SNX_XFER_LINEAR_BYTES],
        (unsigned long long)snx_transfer_counts[SNX_XFER_DST_BYTES]);
    memset(snx_transfer_counts, 0, sizeof snx_transfer_counts);
    snx_transfer_hits = snx_transfer_misses = snx_transfer_evicted = 0;
}
#endif
