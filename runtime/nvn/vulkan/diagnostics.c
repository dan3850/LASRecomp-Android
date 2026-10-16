#include "vk.h"
#include "diagnostics.h"
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

// Fixed-size evidence, independent of the runtime log's tail. Never records ROM
// bytes, GLSL source, SAF paths or fonts. Errors keep counters even when sampled.
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned long long counts[VD_COUNT];
static char events[256][384], info[8192];
static unsigned event_count;
static size_t info_size;
static atomic_bool requested;
static atomic_uint trace_count;
#ifndef LASRECOMP_BUILD_SHA
#define LASRECOMP_BUILD_SHA "unknown"
#endif
static const char *names[VD_COUNT] = {"textures_created", "bcn_cpu_uploads", "unsupported_formats",
    "uploads_skipped", "r8_linear_uploads", "zero_global_memory_bindings", "shader_errors",
    "pipeline_errors", "missing_texture_bindings", "captures", "info", "capture_draws"};

void vk_diag_event(unsigned kind, const char *fmt, ...) {
    if (kind >= VD_COUNT) return;
    pthread_mutex_lock(&lock);
    unsigned long long n = ++counts[kind];
    // Preserve first occurrences and logarithmically sampled repeats, not per-draw I/O.
    if (n <= 8 || !(n & (n - 1)) || kind == VD_CAPTURE || kind == VD_DRAW) {
        char *dst = events[event_count++ & 255];
        int len = snprintf(dst, 384, "%s #%llu: ", names[kind], n);
        va_list ap; va_start(ap, fmt);
        vsnprintf(dst + len, 384 - (size_t)len, fmt, ap);
        va_end(ap);
        LOG("[graphics] %s\n", dst);
        mkdir("graphics", 0700);
        FILE *log = fopen("graphics/events.txt", event_count == 1 ? "w" : "a");
        if (log) { fprintf(log, "%s\n", dst); fclose(log); }
    }
    pthread_mutex_unlock(&lock);
}
void vk_diag_info(const char *fmt, ...) {
    pthread_mutex_lock(&lock);
    if (info_size < sizeof info - 2) {
        va_list ap; va_start(ap, fmt);
        int n = vsnprintf(info + info_size, sizeof info - info_size - 1, fmt, ap);
        va_end(ap);
        if (n > 0) {
            size_t room = sizeof info - info_size - 2;
            info_size += (size_t)n < room ? (size_t)n : room;
            info[info_size++] = '\n'; info[info_size] = 0;
        }
    }
    mkdir("graphics", 0700);
    FILE *f = fopen("graphics/device.txt", "w");
    if (f) { fprintf(f, "build=%s\nGPU=%s\n%s", LASRECOMP_BUILD_SHA, g_vk.props.deviceName, info); fclose(f); }
    pthread_mutex_unlock(&lock);
}
__attribute__((visibility("default")))
int lasrecomp_graphics_capture_request(void) {
    if (atomic_load(&requested)) return 0;
    atomic_store(&trace_count, 0);
    return !atomic_exchange(&requested, true);
}
bool vk_diag_trace_draw(void) {
    return atomic_load_explicit(&requested, memory_order_relaxed) && atomic_fetch_add(&trace_count, 1) < 128;
}
static void state(const char *value) {
    FILE *f = fopen("graphics/capture.state.tmp", "w");
    if (!f) return;
    fputs(value, f);
    if (!fclose(f)) rename("graphics/capture.state.tmp", "graphics/capture.state");
}
bool vk_diag_begin_capture(void) {
    if (!atomic_exchange(&requested, false)) return false;
    if (mkdir("graphics", 0700) && access("graphics", W_OK)) {
        LOG("[graphics] cannot create capture directory\n"); return false;
    }
    state("busy\n");
    unlink("graphics/frame.png");
    unlink("graphics/report.txt");
    for (int i = 0; i < 4; i++) {
        char p[80];
        snprintf(p, sizeof p, "graphics/atlas-%d-cpu.png", i); unlink(p);
        snprintf(p, sizeof p, "graphics/atlas-%d-gpu.png", i); unlink(p);
    }
    vk_diag_event(VD_CAPTURE, "requested at presented frame %llu", (unsigned long long)renderer_present_count());
    return true;
}
void vk_diag_finish_capture(bool frame_saved) {
    FILE *f = fopen("graphics/report.txt.tmp", "w");
    if (!f) { state("error: report could not be written\n"); return; }
    fprintf(f, "LASRecomp graphics capture v1\nBuild: %s\nFrame: %llu\nScreenshot: %s\nGPU: %s\nVulkan: %u.%u.%u\nDriver: %u\n"
        "host_memory_import_extension: %d\nswapchain: %ux%u format=%d\n",
        LASRECOMP_BUILD_SHA, (unsigned long long)renderer_present_count(), frame_saved ? "saved" : "failed",
        g_vk.props.deviceName, VK_VERSION_MAJOR(g_vk.props.apiVersion), VK_VERSION_MINOR(g_vk.props.apiVersion),
        VK_VERSION_PATCH(g_vk.props.apiVersion), g_vk.props.driverVersion, g_vk.host_import,
        g_vk.sc_extent.width, g_vk.sc_extent.height, g_vk.sc_format);
    pthread_mutex_lock(&lock);
    fprintf(f, "\nCapabilities and initialization\n%s\nCounters since renderer initialization\n", info);
    for (unsigned i = 0; i < VD_COUNT; i++) fprintf(f, "%s=%llu\n", names[i], counts[i]);
    fputs("\nSampled events, oldest first; capture_draws covers only draws between request and capture\n", f);
    for (unsigned i = event_count > 256 ? event_count - 256 : 0; i < event_count; i++) fprintf(f, "%s\n", events[i & 255]);
    pthread_mutex_unlock(&lock);
    fputs("\nLive textures (bounded inventory)\n", f);
    vk_diag_texture_report(f);
    bool ok = !ferror(f);
    if (fclose(f)) ok = false;
    if (ok && rename("graphics/report.txt.tmp", "graphics/report.txt")) ok = false;
    state(ok ? (frame_saved ? "complete\n" : "error: screenshot failed; report available\n") : "error: report write failed\n");
}
