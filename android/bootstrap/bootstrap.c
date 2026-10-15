/*
 * Phase 1: Android native window and Vulkan-loader smoke test.
 * Not the LASRecomp runtime or game yet. No game files are used.
 */
#include <android/log.h>
#include <android/native_activity.h>
#include <android/native_window.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if !defined(__aarch64__)
#error "This bootstrap intentionally supports arm64-v8a only."
#endif

#define TAG "LASRecompAndroid"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

typedef struct {
    int vulkan_loader_found;
} AppState;

/* 5x7 pixel font for an offline, Java-free boot status screen. */
static const uint8_t glyphs[36][7] = {
    {14,17,17,31,17,17,17}, {30,17,17,30,17,17,30},
    {14,17,16,16,16,17,14}, {30,17,17,17,17,17,30},
    {31,16,16,30,16,16,31}, {31,16,16,30,16,16,16},
    {14,17,16,23,17,17,14}, {17,17,17,31,17,17,17},
    {31,4,4,4,4,4,31}, {7,2,2,2,18,18,12},
    {17,18,20,24,20,18,17}, {16,16,16,16,16,16,31},
    {17,27,21,21,17,17,17}, {17,25,21,19,17,17,17},
    {14,17,17,17,17,17,14}, {30,17,17,30,16,16,16},
    {14,17,17,17,21,18,13}, {30,17,17,30,20,18,17},
    {15,16,16,14,1,1,30}, {31,4,4,4,4,4,4},
    {17,17,17,17,17,17,14}, {17,17,17,17,17,10,4},
    {17,17,17,21,21,21,10}, {17,17,10,4,10,17,17},
    {17,17,10,4,4,4,4}, {31,1,2,4,8,16,31},
    {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14},
    {14,17,1,2,4,8,31}, {30,1,1,14,1,1,30},
    {2,6,10,18,31,2,2}, {31,16,30,1,1,17,14},
    {6,8,16,30,17,17,14}, {31,1,2,4,8,8,8},
    {14,17,17,14,17,17,14}, {14,17,17,15,1,2,12}
};

static const uint8_t *glyph(char c) {
    if (c >= 'A' && c <= 'Z') return glyphs[c - 'A'];
    if (c >= '0' && c <= '9') return glyphs[26 + c - '0'];
    return NULL;
}

static void pixel(ANativeWindow_Buffer *b, int x, int y, uint32_t color) {
    if (x < 0 || y < 0 || x >= b->width || y >= b->height) return;
    ((uint32_t *)b->bits)[(size_t)y * b->stride + x] = color;
}

static void write_line(ANativeWindow_Buffer *b, const char *s, int y,
                       int scale, uint32_t color) {
    int len = (int)strlen(s);
    int x0 = (b->width - len * 6 * scale) / 2;
    for (int k = 0; k < len; k++) {
        const uint8_t *rows = glyph(s[k]);
        if (!rows) continue;
        for (int j = 0; j < 7; j++) for (int i = 0; i < 5; i++)
            if (rows[j] & (1u << (4 - i)))
                for (int yy = 0; yy < scale; yy++)
                    for (int xx = 0; xx < scale; xx++)
                        pixel(b, x0 + (k * 6 + i) * scale + xx,
                              y + j * scale + yy, color);
    }
}

static void draw_status(ANativeWindow *window, int vulkan_found) {
    if (!window) return;
    if (ANativeWindow_setBuffersGeometry(window, 0, 0,
                                         WINDOW_FORMAT_RGBA_8888) != 0) {
        LOGE("Failed to set window buffer format");
        return;
    }
    ANativeWindow_Buffer b;
    if (ANativeWindow_lock(window, &b, NULL) != 0) {
        LOGE("Failed to lock native window");
        return;
    }
    for (int y = 0; y < b.height; y++) {
        uint32_t *row = (uint32_t *)b.bits + (size_t)y * b.stride;
        for (int x = 0; x < b.width; x++) row[x] = 0xff1b1123u;
    }
    int scale = b.width / 150;
    int vscale = b.height / 55;
    if (scale > vscale) scale = vscale;
    if (scale < 1) scale = 1;
    if (scale > 8) scale = 8;
    int top = (b.height - 4 * 11 * scale) / 2;
    write_line(&b, "LASRECOMP ANDROID", top, scale, 0xffeeeeffu);
    write_line(&b, "ARM64 BOOTSTRAP", top + 11 * scale, scale, 0xffa9c6ffu);
    write_line(&b, vulkan_found ? "VULKAN LOADER FOUND" : "VULKAN LOADER MISSING",
               top + 22 * scale, scale, vulkan_found ? 0xff9be7b4u : 0xff7777ffu);
    write_line(&b, "NO GAME CODE YET", top + 33 * scale, scale, 0xffd3b2f5u);
    ANativeWindow_unlockAndPost(window);
}

static int probe_vulkan(void) {
    void *lib = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if (!lib) {
        LOGE("libvulkan.so missing: %s", dlerror());
        return 0;
    }
    typedef int32_t (*EnumerateVersion)(uint32_t *);
    EnumerateVersion enumerate = (EnumerateVersion)dlsym(lib, "vkEnumerateInstanceVersion");
    if (enumerate) {
        uint32_t version = 0;
        if (enumerate(&version) == 0)
            LOGI("Vulkan loader API version %u.%u.%u",
                 version >> 22, (version >> 12) & 1023u, version & 4095u);
        else
            LOGE("vkEnumerateInstanceVersion returned an error");
    } else {
        LOGI("Vulkan loader present; API version query unavailable");
    }
    dlclose(lib);
    return 1; /* Loader presence is NOT proof of a working Vulkan renderer. */
}

static void on_window(ANativeActivity *activity, ANativeWindow *window) {
    AppState *state = (AppState *)activity->instance;
    draw_status(window, state ? state->vulkan_loader_found : 0);
    LOGI("Native window ready: %dx%d", ANativeWindow_getWidth(window),
         ANativeWindow_getHeight(window));
}

static void on_destroy(ANativeActivity *activity) {
    LOGI("NativeActivity destroyed");
    free(activity->instance);
    activity->instance = NULL;
}

__attribute__((visibility("default")))
void ANativeActivity_onCreate(ANativeActivity *activity, void *saved_state,
                              size_t saved_state_size) {
    (void)saved_state;
    (void)saved_state_size;
    AppState *state = (AppState *)calloc(1, sizeof(*state));
    if (!state) {
        LOGE("Out of memory creating state");
        return;
    }
    activity->instance = state;
    activity->callbacks->onNativeWindowCreated = on_window;
    activity->callbacks->onNativeWindowRedrawNeeded = on_window;
    activity->callbacks->onDestroy = on_destroy;
    state->vulkan_loader_found = probe_vulkan();
    LOGI("LASRecomp Android phase 1 started; ABI arm64-v8a, native bootstrap only");
}
