/* SPDX-License-Identifier: MIT
 * Included once, in renderer.c. Samples are copied under a short lock; sorting
 * and logging happen after releasing it. No device query or GPU wait is added.
 */
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "nx/runtime/snx_perf.h"
#include "nx/runtime/snx_perf_build.h"

#define SNX_PERF_SAMPLES 4096
int snx_perf_on;
static PMutex snx_perf_lock = PMUTEX_INIT;
static const char* const snx_pm_names[SNX_PM_COUNT] = {
    "timeline", "recycle", "record_sync", "submit", "present_api", "acquire",
    "pace", "jit_wait", "jit_compile", "jit_failed", "no_image", "render_cpu", "wait_elided",
    "texture_hash", "hash_bytes", "texture_upload_cpu"
};
static const char* const snx_pf_names[SNX_PF_COUNT] = {"guest_queue", "render", "present_enqueue"};
static u64 snx_pm_ns[SNX_PM_COUNT], snx_pm_n[SNX_PM_COUNT];
typedef struct {
    u64 last, frames, n, lost;
    u64 dt[SNX_PERF_SAMPLES];
} SnxPerfStream;
static SnxPerfStream snx_pf[SNX_PF_COUNT], snx_pf_copy[SNX_PF_COUNT];
static u64 snx_perf_start, snx_perf_since, snx_perf_window;

void snx_perf_init(void) {
    const char* e = getenv("SNX_PERF");
    snx_perf_on = e && strcmp(e, "0");
    if (!snx_perf_on) return;
    snx_perf_start = snx_perf_since = plat_ns();
    const char* ryu = getenv("SNX_RYUJINX_NATIVE_PROBE");
    const char* cache = getenv("SNX_RYU_PERSIST");
    const char* known = getenv("SNX_VK_KNOWN_COMPLETE");
    LOG("SNX_PERF_META_V1 {\"revision\":\"%s\",\"ryujinx_requested\":%d,\"cache_requested\":%d,"
        "\"known_complete\":%d,\"displayed_fps\":null}\n", SNX_PERF_REVISION,
        ryu && !strcmp(ryu, "1"), cache && !strcmp(cache, "1"), known && !strcmp(known, "1"));
}
void snx_perf_add(int metric, u64 ns, u64 count) {
    if (!snx_perf_on) return;
    __atomic_add_fetch(&snx_pm_ns[metric], ns, __ATOMIC_RELAXED);
    __atomic_add_fetch(&snx_pm_n[metric], count, __ATOMIC_RELAXED);
}
static int snx_perf_cmp(const void* a, const void* b) {
    u64 x = *(const u64*)a, y = *(const u64*)b;
    return x < y ? -1 : x > y ? 1 : 0;
}
static void snx_perf_samples(const SnxPerfStream* s, int stream, u64 window, double ms) {
    char line[1600];
    /* Each JSON line fits inside ScarletNX's 2048-byte logging buffer. Raw
       microsecond intervals allow exact pooled percentiles in the analyzer. */
    for (u64 at = 0; at < s->n;) {
        size_t len = (size_t)snprintf(line, sizeof line,
            "SNX_FRAMES_V1 {\"window\":%llu,\"stream\":\"%s\",\"us\":[",
            (unsigned long long)window, snx_pf_names[stream]);
        for (int i = 0; i < 64 && at < s->n; i++, at++)
            len += (size_t)snprintf(line + len, sizeof line - len, "%s%llu", i ? "," : "",
                                  (unsigned long long)(s->dt[at] / 1000));
        snprintf(line + len, sizeof line - len, "]}");
        LOG("%s\n", line);
    }
    /* Work on the copy only: a stream's last timestamp survives the window. */
    u64 sorted[SNX_PERF_SAMPLES];
    memcpy(sorted, s->dt, (size_t)s->n * sizeof sorted[0]);
    qsort(sorted, (size_t)s->n, sizeof sorted[0], snx_perf_cmp);
    double p50 = s->n ? (double)sorted[(s->n * 50 + 99) / 100 - 1] / 1e6 : 0;
    double p95 = s->n ? (double)sorted[(s->n * 95 + 99) / 100 - 1] / 1e6 : 0;
    double p99 = s->n ? (double)sorted[(s->n * 99 + 99) / 100 - 1] / 1e6 : 0;
    LOG("SNX_STREAM_V1 {\"window\":%llu,\"stream\":\"%s\",\"frames\":%llu,\"fps\":%.3f,"
        "\"samples\":%llu,\"lost\":%llu,\"p50_ms\":%.3f,\"p95_ms\":%.3f,\"p99_ms\":%.3f}\n",
        (unsigned long long)window, snx_pf_names[stream], (unsigned long long)s->frames,
        ms > 0 ? (double)s->frames * 1000.0 / ms : 0, (unsigned long long)s->n,
        (unsigned long long)s->lost, p50, p95, p99);
}
u64 snx_perf_frame(int stream) {
    if (!snx_perf_on) return 0;
    u64 now = plat_ns(), window = 0, duration = 0;
    pm_lock(&snx_perf_lock);
    SnxPerfStream* s = &snx_pf[stream];
    s->frames++;
    if (s->last) {
        if (s->n < SNX_PERF_SAMPLES) s->dt[s->n++] = now - s->last;
        else s->lost++;
    }
    s->last = now;
    if (stream == SNX_PF_RENDER && now - snx_perf_since >= 5000000000ull) {
        duration = now - snx_perf_since;
        snx_perf_since = now;
        window = ++snx_perf_window;
        memcpy(snx_pf_copy, snx_pf, sizeof snx_pf);
        for (int i = 0; i < SNX_PF_COUNT; i++) snx_pf[i].frames = snx_pf[i].n = snx_pf[i].lost = 0;
    }
    pm_unlock(&snx_perf_lock);
    if (!window) return 0;
    double ms = (double)duration / 1e6;
    LOG("SNX_PERF_V1 {\"window\":%llu,\"elapsed_s\":%.3f,\"duration_ms\":%.3f}\n",
        (unsigned long long)window, (double)(now - snx_perf_start) / 1e9, ms);
    for (int i = 0; i < SNX_PF_COUNT; i++) snx_perf_samples(&snx_pf_copy[i], i, window, ms);
    for (int i = 0; i < SNX_PM_COUNT; i++) {
        u64 ns = __atomic_exchange_n(&snx_pm_ns[i], 0, __ATOMIC_RELAXED);
        u64 n = __atomic_exchange_n(&snx_pm_n[i], 0, __ATOMIC_RELAXED);
        LOG("SNX_COST_V1 {\"window\":%llu,\"metric\":\"%s\",\"calls\":%llu,\"ms\":%.3f}\n",
            (unsigned long long)window, snx_pm_names[i], (unsigned long long)n, (double)ns / 1e6);
    }
    return window;
}
