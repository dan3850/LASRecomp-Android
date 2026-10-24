/* SPDX-License-Identifier: MIT
 * Full clears at a new pass begin. No deferred writes or cross-pass lookahead.
 * Included by render.c; all state and counters run under vk_lock.
 */
#ifndef SNX_CLEAR_LOAD_H
#define SNX_CLEAR_LOAD_H
typedef struct {
    int color_slot, applied;
    u32 ds;
    VkClearValue color;
    VkClearDepthStencilValue depth;
} SnxClearLoad;
enum {
    SNX_CL_REQUESTS, SNX_CL_CANDIDATES, SNX_CL_FOLDED, SNX_CL_CONTINUED,
    SNX_CL_COLOR, SNX_CL_DEPTH, SNX_CL_STENCIL,
    SNX_CL_COLOR_PIXELS, SNX_CL_DEPTH_PIXELS, SNX_CL_STENCIL_PIXELS, SNX_CL_COUNT
};
static u64 snx_clear_counts[SNX_CL_COUNT];
int snx_clear_load_on(void) {
    static int mode = -1;
    if (mode < 0) {
        const char* e = getenv("SNX_VK_CLEAR_LOAD");
        mode = e && !strcmp(e, "1");
        LOG("SNX_CLEAR_LOAD_META_V1 {\"enabled\":%d,\"immediate\":1,\"single_layer\":1}\n", mode);
    }
    return mode;
}
static int snx_clear_load_prepare(const GpuChannel* ch, u32 v, Surf** rt, Surf* zt, u32 n,
                                  float dz, SnxClearLoad* out) {
    memset(out, 0, sizeof *out);
    out->color_slot = -1;
    if (!snx_clear_load_on()) return 0;
    snx_clear_counts[SNX_CL_REQUESTS]++;
    u32 mask = (v >> 2) & 15, slot = (v >> 6) & 15;
    if (ch->render_pred || r3d_clear_scissored(ch->r3d) || ((v >> 10) & 0x7ff) || n > 8 ||
        (mask && (mask != 15 || slot >= n || !rt[slot]))) return 0;
    u32 ds = zt ? (v & 1) | ((zt->f.stencil && (v & 2)) ? 2u : 0u) : 0;
    /* One shared depth/stencil attachment description: preserve either aspect
       that a partial clear would leave intact by keeping the original command. */
    if (ds && ds != (zt->f.stencil ? 3u : 1u)) return 0;
    if (!mask && !ds) return 0;
    u32 width = 0, height = 0, count = 0;
    VkImage seen[9];
    for (u32 i = 0; i <= n; i++) {
        Surf* s = i == n ? zt : rt[i];
        if (!s) continue;
        if (!s->img || s->layers != 1 || s->volume || s->depth3d > 1 || !s->sw || !s->sh) return 0;
        if (count && (s->sw != width || s->sh != height)) return 0;
        for (u32 j = 0; j < count; j++) if (seen[j] == s->img) return 0;
        seen[count++] = s->img;
        width = s->sw;
        height = s->sh;
    }
    if (!count) return 0;
    if (mask) {
        out->color_slot = (int)slot;
        /* Integer registers and float registers both retain their exact bits. */
        memcpy(&out->color.color, &ch->r3d[0x360], 16);
    }
    out->ds = ds;
    out->depth = (VkClearDepthStencilValue){dz, ch->r3d[0x368] & 0xff};
    snx_clear_counts[SNX_CL_CANDIDATES]++;
    return 1;
}
static void snx_clear_load_used(const SnxClearLoad* load, VkExtent2D extent) {
    u64 pixels = (u64)extent.width * extent.height;
    snx_clear_counts[SNX_CL_FOLDED]++;
    if (load->color_slot >= 0) { snx_clear_counts[SNX_CL_COLOR]++; snx_clear_counts[SNX_CL_COLOR_PIXELS] += pixels; }
    if (load->ds & 1) { snx_clear_counts[SNX_CL_DEPTH]++; snx_clear_counts[SNX_CL_DEPTH_PIXELS] += pixels; }
    if (load->ds & 2) { snx_clear_counts[SNX_CL_STENCIL]++; snx_clear_counts[SNX_CL_STENCIL_PIXELS] += pixels; }
}
void snx_clear_load_report(u64 window) {
    LOG("SNX_CLEAR_LOAD_V1 {\"window\":%llu,\"enabled\":%d,\"requests\":%llu,\"candidates\":%llu,"
        "\"folded_commands\":%llu,\"continued_fallbacks\":%llu,\"color_clears\":%llu,"
        "\"depth_clears\":%llu,\"stencil_clears\":%llu,\"color_pixels\":%llu,"
        "\"depth_pixels\":%llu,\"stencil_pixels\":%llu}\n",
        (unsigned long long)window, snx_clear_load_on(),
        (unsigned long long)snx_clear_counts[SNX_CL_REQUESTS], (unsigned long long)snx_clear_counts[SNX_CL_CANDIDATES],
        (unsigned long long)snx_clear_counts[SNX_CL_FOLDED], (unsigned long long)snx_clear_counts[SNX_CL_CONTINUED],
        (unsigned long long)snx_clear_counts[SNX_CL_COLOR], (unsigned long long)snx_clear_counts[SNX_CL_DEPTH],
        (unsigned long long)snx_clear_counts[SNX_CL_STENCIL], (unsigned long long)snx_clear_counts[SNX_CL_COLOR_PIXELS],
        (unsigned long long)snx_clear_counts[SNX_CL_DEPTH_PIXELS], (unsigned long long)snx_clear_counts[SNX_CL_STENCIL_PIXELS]);
    memset(snx_clear_counts, 0, sizeof snx_clear_counts);
}
#endif
