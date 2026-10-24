/* SPDX-License-Identifier: MIT
 * Graphics uniform snapshots in the existing immutable staging ring.
 * Included by buffer.c; all calls and counters run under vk_lock.
 */
#ifndef SNX_UNIFORM_H
#define SNX_UNIFORM_H
enum {
    SNX_U_REQUESTS, SNX_U_REUSED, SNX_U_REUSED_BYTES,
    SNX_U_PROMOTION_BYPASS, SNX_U_STAGED, SNX_U_STAGED_BYTES, SNX_U_COUNT
};
static u64 snx_uniform_counts[SNX_U_COUNT];
int snx_uniform_on(void) {
    static int mode = -1;
    if (mode < 0) {
        const char* e = getenv("SNX_VK_UNIFORM_STREAM");
        mode = e && !strcmp(e, "1");
        LOG("SNX_UNIFORM_META_V1 {\"enabled\":%d,\"strict_checks\":1,\"max_bytes\":65536}\n", mode);
    }
    return mode;
}
void snx_uniform_report(u64 window) {
    LOG("SNX_UNIFORM_V1 {\"window\":%llu,\"enabled\":%d,\"requests\":%llu,"
        "\"reused_snapshots\":%llu,\"reused_bytes\":%llu,\"promotion_bypasses\":%llu,"
        "\"staged_snapshots\":%llu,\"staged_bytes\":%llu}\n",
        (unsigned long long)window, snx_uniform_on(),
        (unsigned long long)snx_uniform_counts[SNX_U_REQUESTS],
        (unsigned long long)snx_uniform_counts[SNX_U_REUSED],
        (unsigned long long)snx_uniform_counts[SNX_U_REUSED_BYTES],
        (unsigned long long)snx_uniform_counts[SNX_U_PROMOTION_BYPASS],
        (unsigned long long)snx_uniform_counts[SNX_U_STAGED],
        (unsigned long long)snx_uniform_counts[SNX_U_STAGED_BYTES]);
    memset(snx_uniform_counts, 0, sizeof snx_uniform_counts);
}
#endif
