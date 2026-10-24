/* SPDX-License-Identifier: MIT
 * Range-qualified texture hash reads. Included in texture.c under vk_lock.
 * Keep the original whole-content hash and the original owned-byte fallback.
 */
#ifndef SNX_ZELDA_HASH_SPAN_H
#define SNX_ZELDA_HASH_SPAN_H
#include "nx/memory/mem.h"
static int snx_hash_span_on;
static u64 snx_hash_span_counts[5];
/* Checks, direct calls/bytes, owned-page fallback, noncontiguous fallback. */
void snx_hash_span_init(void) {
    const char* option = getenv("SNX_VK_HASH_SPAN");
    snx_hash_span_on = option && !strcmp(option, "1");
    LOG("SNX_HASH_SPAN_META_V1 {\"enabled\":%d,\"all_bytes_checked\":1}\n", snx_hash_span_on);
}
static u8* snx_hash_span_ptr(u64 gva, u64 size) {
    if (!snx_hash_span_on || !size) return NULL;
    snx_hash_span_counts[0]++;
    /* No dereference and no ownership acquisition while qualifying the range.
       gmem_host, unlike gmem_ptr, never lands a GPU result. */
    u8* p = gmem_host(gva, size);
    if (!p) {
        snx_hash_span_counts[4]++;
        return NULL;
    }
    /* Preserve visibility of pending compute, graphics and release writes.
       They may publish a new owner, so test ownership AFTER this call. */
    gmem_need(gva, size);
    p = gmem_host(gva, size);
    if (!p) {
        snx_hash_span_counts[4]++;
        return NULL;
    }
    u64 ignored = 0;
    /* The real ownership helper rounds to host pages, including an owner
       outside the bytes on a shared 4/16 KiB page. vk_lock prevents new GPU
       owners or mapping changes while the returned span is hashed. */
    if (own_hash((u64)(p - g_mem), size, &ignored)) {
        snx_hash_span_counts[3]++;
        return NULL;
    }
    /* Reuse the public CPU-readable-pointer contract. No owned page remains
       to acquire here; never use this function before the page-range proof. */
    p = gmem_ptr_untracked(gva, size);
    if (!p) {
        snx_hash_span_counts[4]++;
        return NULL;
    }
    snx_hash_span_counts[1]++;
    snx_hash_span_counts[2] += size;
    return p;
}
void snx_hash_span_report(u64 window) {
    LOG("SNX_HASH_SPAN_V1 {\"window\":%llu,\"enabled\":%d,\"checks\":%llu,"
        "\"direct_calls\":%llu,\"direct_bytes\":%llu,\"owned_fallback\":%llu,"
        "\"noncontiguous_fallback\":%llu}\n",
        (unsigned long long)window, snx_hash_span_on,
        (unsigned long long)snx_hash_span_counts[0], (unsigned long long)snx_hash_span_counts[1],
        (unsigned long long)snx_hash_span_counts[2], (unsigned long long)snx_hash_span_counts[3],
        (unsigned long long)snx_hash_span_counts[4]);
    memset(snx_hash_span_counts, 0, sizeof snx_hash_span_counts);
}
#endif
