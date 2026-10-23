/* SPDX-License-Identifier: MIT
 * A lower bound confirmed by SUCCESSFUL host waits on this graphics timeline.
 * An acquire/release atomic carries the confirmation between CPU threads.
 * This never predicts completion, polls the driver, submits work, touches a
 * compute/present semaphore, or removes a HOST barrier/allocation invalidate.
 */
static int snx_known_on;
static u64 snx_known_completed;
static void snx_known_init(void) {
    const char* e = getenv("SNX_VK_KNOWN_COMPLETE");
    snx_known_on = e && !strcmp(e, "1");
    __atomic_store_n(&snx_known_completed, 0, __ATOMIC_RELEASE);
    LOG("vulkan: SNX_KNOWN_COMPLETE_V1: %s (successful graphics host waits only)\n",
        snx_known_on ? "ON" : "OFF");
}
static int snx_known_ready(u64 value) {
    return snx_known_on && value <= __atomic_load_n(&snx_known_completed, __ATOMIC_ACQUIRE);
}
static void snx_known_note(u64 value) {
    if (!snx_known_on) return;
    u64 old = __atomic_load_n(&snx_known_completed, __ATOMIC_RELAXED);
    while (old < value && !__atomic_compare_exchange_n(&snx_known_completed, &old, value, 1,
                                                       __ATOMIC_RELEASE, __ATOMIC_RELAXED)) {}
}
