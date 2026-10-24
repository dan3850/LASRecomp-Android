/* Exercise the actual device-selection snippet, actual old/new viewport
 * functions and installed helper. No Vulkan driver or private game data. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { float x, y, width, height, minDepth, maxDepth; } VkViewport;
typedef struct { char extensionName[256]; u32 specVersion; } VkExtensionProperties;
#define VK_KHR_SWAPCHAIN_EXTENSION_NAME "VK_KHR_swapchain"
#define VK_EXT_VERTEX_ATTRIBUTE_DIVISOR_EXTENSION_NAME "VK_EXT_vertex_attribute_divisor"
#define VK_EXT_TRANSFORM_FEEDBACK_EXTENSION_NAME "VK_EXT_transform_feedback"
#define VK_EXT_CUSTOM_BORDER_COLOR_EXTENSION_NAME "VK_EXT_custom_border_color"
#define VK_KHR_SHADER_CLOCK_EXTENSION_NAME "VK_KHR_shader_clock"
#define VK_EXT_ATTACHMENT_FEEDBACK_LOOP_LAYOUT_EXTENSION_NAME "VK_EXT_attachment_feedback_loop_layout"
#define VK_EXT_ATTACHMENT_FEEDBACK_LOOP_DYNAMIC_STATE_EXTENSION_NAME "VK_EXT_attachment_feedback_loop_dynamic_state"
#define VK_KHR_DYNAMIC_RENDERING_LOCAL_READ_EXTENSION_NAME "VK_KHR_dynamic_rendering_local_read"
#define VK_EXT_CONDITIONAL_RENDERING_EXTENSION_NAME "VK_EXT_conditional_rendering"
#define VK_EXT_PROVOKING_VERTEX_EXTENSION_NAME "VK_EXT_provoking_vertex"
#define VK_EXT_MEMORY_BUDGET_EXTENSION_NAME "VK_EXT_memory_budget"
#define VK_EXT_DEPTH_RANGE_UNRESTRICTED_EXTENSION_NAME "VK_EXT_depth_range_unrestricted"
#define VK_KHR_VIDEO_QUEUE_EXTENSION_NAME "VK_KHR_video_queue"
#define VK_KHR_VIDEO_DECODE_QUEUE_EXTENSION_NAME "VK_KHR_video_decode_queue"
#define VK_KHR_VIDEO_DECODE_H264_EXTENSION_NAME "VK_KHR_video_decode_h264"
static struct {
    const char* dev_ext[32]; u32 dev_ext_n;
    int depth_range_requested, has_depth_range, depth_range_enabled;
    int has_divisor, has_xfb, has_border_color, has_feedback, has_local_read, phys;
} g_vk;
static int g_opt_headless, support, enum_calls, log_calls;
static int snx_perf_on = 1;
static float resolution = 1;
static float vk_scf(float x) { return x * resolution; }
#define LOG(...) do { log_calls++; printf(__VA_ARGS__); } while (0)
#define LOG_LIMIT(n, ...) do {} while (0)
static void vkEnumerateDeviceExtensionProperties(int pd, void* layer, u32* n, VkExtensionProperties* e) {
    (void)pd; (void)layer; enum_calls++;
    if (!e) { *n = support ? 1 : 0; return; }
    if (support) strcpy(e[0].extensionName, VK_EXT_DEPTH_RANGE_UNRESTRICTED_EXTENSION_NAME);
}
#include "depth_gate_actual.inc"
#include "depth_before_actual.inc"
#include "depth_range.h"
#include "depth_after_actual.inc"
static void put(u32* r, unsigned index, float x) { memcpy(r + index, &x, 4); }
static void closef(float a, float b) { assert(fabsf(a - b) < 0.000004f); }

int main(void) {
    const char* modes[] = {NULL, "0", "1", "true", "01"};
    for (int present = 0; present < 2; present++) for (int i = 0; i < 5; i++) {
        if (modes[i]) setenv("SNX_VK_DEPTH_RANGE", modes[i], 1); else unsetenv("SNX_VK_DEPTH_RANGE");
        support = present; enum_calls = 0;
        gate_actual();
        assert(enum_calls == 2 && g_vk.has_depth_range == present);
        assert(g_vk.depth_range_requested == (i == 2));
        assert(g_vk.depth_range_enabled == (present && i == 2));
        assert(g_vk.dev_ext_n == (u32)(1 + (present && i == 2)));
        if (g_vk.depth_range_enabled)
            assert(!strcmp(g_vk.dev_ext[1], VK_EXT_DEPTH_RANGE_UNRESTRICTED_EXTENSION_NAME));
        snx_depth_range_init();
    }
    u32 r[0x1000] = {0}; r[0x64b] = 1; r[0x3fe] = 2048u << 16;
    put(r,0x280,1024); put(r,0x281,1024); put(r,0x283,1024); put(r,0x284,1024);
    put(r,0x302,0); put(r,0x303,1);
    unsigned vectors = 0;
    const float scales[] = {1, .5f, -1, .25f, 0};
    const float offsets[] = {0, .5f, 1, -.25f};
    for (unsigned scale = 0; scale < 5; scale++) for (unsigned off = 0; off < 4; off++)
    for (unsigned mode = 0; mode < 2; mode++) for (unsigned flip = 0; flip < 4; flip++) {
        r[0x35f] = mode; r[0x4eb] = flip & 1; r[0x286] = (flip & 2) ? 3u << 4 : 0;
        resolution = flip & 1 ? .5f : 1; put(r,0x282,scales[scale]); put(r,0x285,offsets[off]);
        VkViewport before = before_actual(r);
        g_vk.depth_range_enabled = 0;
        VkViewport after = after_actual(r);
        assert(!memcmp(&before,&after,sizeof before));
        g_vk.depth_range_enabled = 1; after = after_actual(r);
        assert(!memcmp(&before,&after,4 * sizeof(float)));
        if (scales[scale] != 0 || offsets[off] != 0) {
            const float points[] = {0,.2f,.5f,.8f,1};
            for (unsigned j = 0; j < 5; j++) {
                float z = points[j];
                float clip = mode ? z : (z + 1) * .5f;
                float mapped = clip * (after.maxDepth - after.minDepth) + after.minDepth;
                closef(mapped,z * scales[scale] + offsets[off]);
            }
        }
        vectors++;
    }
    /* Captured shadow state: old 0.2 -> 0.6; preserved range 0.2 -> 0.2. */
    memset(r,0,sizeof r); r[0x64b] = 1; r[0x4eb] = 0x10; r[0x64f] = 0x181d;
    put(r,0x280,1024); put(r,0x281,1024); put(r,0x282,1);
    put(r,0x283,1024); put(r,0x284,1024); put(r,0x303,1);
    VkViewport old = before_actual(r); g_vk.depth_range_enabled = 1;
    VkViewport fixed = after_actual(r);
    assert(old.minDepth == 0 && old.maxDepth == 1 && fixed.minDepth == -1 && fixed.maxDepth == 1);
    closef(.6f * (old.maxDepth-old.minDepth)+old.minDepth,.6f);
    closef(.6f * (fixed.maxDepth-fixed.minDepth)+fixed.minDepth,.2f);
    for (unsigned j=0;j<10;j++) snx_depth_range_note(r,&fixed);
    assert(snx_depth_states == 4 && snx_depth_draws == 10 && snx_depth_unrestricted == 10);
    snx_depth_range_report(1); assert(!snx_depth_draws && !snx_depth_unrestricted);
    snx_perf_on = 0; int logs = log_calls;
    snx_depth_range_note(r,&fixed); snx_depth_range_init();
    assert(log_calls == logs && !snx_depth_draws);
    for (unsigned j=0;j<2;j++) {
        put(r,0x282,j ? NAN : INFINITY);
        old = before_actual(r); fixed = after_actual(r);
        assert(!memcmp(&old,&fixed,sizeof old));
    }
    printf("DEPTH_RANGE_OK vectors=%u off_exact=1 extension_gated=1 mapping_preserved=1\n",vectors);
}
