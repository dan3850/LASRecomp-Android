/* SPDX-License-Identifier: MIT
 * Keep the shader's existing clip-space conversion. With the device extension
 * enabled, preserve its matching viewport range instead of clamping endpoints.
 * Included once by render.c; rendering/reporting run under the existing lock.
 */
#include <math.h>

static u64 snx_depth_draws, snx_depth_unrestricted;
static unsigned snx_depth_states;

void snx_depth_range_init(void) {
    if (!snx_perf_on) return;
    LOG("SNX_DEPTH_RANGE_META_V1 {\"requested\":%d,\"supported\":%d,\"enabled\":%d,"
        "\"shader_changed\":0,\"extra_waits\":0}\n",
        g_vk.depth_range_requested, g_vk.has_depth_range, g_vk.depth_range_enabled);
}

static void snx_depth_range_set(VkViewport* vp, float zn, float zf) {
    if (g_vk.depth_range_enabled && isfinite(zn) && isfinite(zf)) {
        vp->minDepth = zn;
        vp->maxDepth = zf;
    } else {
        vp->minDepth = zn < 0 ? 0 : zn > 1 ? 1 : zn;
        vp->maxDepth = zf < 0 ? 0 : zf > 1 ? 1 : zf;
    }
}

static void snx_depth_range_note(const u32* r, const VkViewport* vp) {
    if (!snx_perf_on) return;
    snx_depth_draws++;
    int outside = vp->minDepth < 0 || vp->minDepth > 1 || vp->maxDepth < 0 || vp->maxDepth > 1;
    if (!outside) return;
    snx_depth_unrestricted++;
    if (snx_depth_states == 4) return;
    snx_depth_states++;
    LOG("SNX_DEPTH_RANGE_STATE_V1 {\"clip_mode_word\":%u,\"clip_control_word\":%u,"
        "\"min_depth\":%.9g,\"max_depth\":%.9g}\n",
        r[0x35f], r[0x64f], (double)vp->minDepth, (double)vp->maxDepth);
}

void snx_depth_range_report(u64 window) {
    LOG("SNX_DEPTH_RANGE_V1 {\"window\":%llu,\"enabled\":%d,\"viewport_setups\":%llu,"
        "\"unrestricted_setups\":%llu}\n", (unsigned long long)window,
        g_vk.depth_range_enabled, (unsigned long long)snx_depth_draws,
        (unsigned long long)snx_depth_unrestricted);
    snx_depth_draws = snx_depth_unrestricted = 0;
}
