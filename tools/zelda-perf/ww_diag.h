/* SPDX-License-Identifier: MIT
 * Passive evidence. No UAPI definitions, probes, protection or policy changes.
 * Reserve/commit bounded events without logging or allocating on error paths;
 * the renderer prints them after telemetry starts and at window boundaries.
 */
#if defined(PAGEMAP_SCAN)
#define SNX_WW_HAS_PAGEMAP 1
#else
#define SNX_WW_HAS_PAGEMAP 0
#endif
#if defined(UFFD_FEATURE_WP_ASYNC)
#define SNX_WW_HAS_ASYNC 1
#else
#define SNX_WW_HAS_ASYNC 0
#endif
#if defined(UFFD_USER_MODE_ONLY)
#define SNX_WW_HAS_USER 1
#else
#define SNX_WW_HAS_USER 0
#endif
#if defined(SYS_userfaultfd)
#define SNX_WW_HAS_SYSCALL 1
#else
#define SNX_WW_HAS_SYSCALL 0
#endif
typedef struct {
    const char* event;
    int error;
    u64 requested, reported;
    unsigned ready;
} SnxWwEvent;
static SnxWwEvent snx_ww_events[16];
static unsigned snx_ww_event_count, snx_ww_printed;
static void snx_ww_note(const char* event, int error, u64 requested, u64 reported) {
    unsigned i = __atomic_fetch_add(&snx_ww_event_count, 1, __ATOMIC_RELAXED);
    if (i >= 16) return;
    SnxWwEvent* e = &snx_ww_events[i];
    e->event = event; e->error = error; e->requested = requested; e->reported = reported;
    __atomic_store_n(&e->ready, 1, __ATOMIC_RELEASE);
}
#if defined(__linux__)
void snx_ww_report(void) {
    static int meta;
    if (!meta) {
        meta = 1;
        LOG("SNX_WW_META_V1 {\"pagemap_uapi\":%d,\"wp_async_uapi\":%d,\"user_mode_uapi\":%d,"
            "\"syscall_uapi\":%d,\"event_limit\":16,\"policy_changed\":0}\n",
            SNX_WW_HAS_PAGEMAP, SNX_WW_HAS_ASYNC, SNX_WW_HAS_USER, SNX_WW_HAS_SYSCALL);
    }
    while (snx_ww_printed < 16) {
        const SnxWwEvent* e = &snx_ww_events[snx_ww_printed];
        if (!__atomic_load_n(&e->ready, __ATOMIC_ACQUIRE)) break;
        LOG("SNX_WW_EVENT_V1 {\"event\":\"%s\",\"errno\":%d,\"requested\":%llu,\"reported\":%llu}\n",
            e->event, e->error, (unsigned long long)e->requested, (unsigned long long)e->reported);
        snx_ww_printed++;
    }
}
#endif
