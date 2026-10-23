/* SPDX-License-Identifier: MIT
 * Detailed-mode resource evidence. Included once by render.c, under vk_lock.
 * Observes existing decisions; never resolves resources or records Vulkan work.
 */
enum { SNX_GFX_PASS_CAP = 64, SNX_GFX_BIND_CAP = 128, SNX_GFX_KEY_WORDS = 14 };
typedef struct {
    u64 key[SNX_GFX_KEY_WORDS];
} SnxGfxKey;
static SnxGfxKey snx_gfx_pass_seen[SNX_GFX_PASS_CAP], snx_gfx_bind_seen[SNX_GFX_BIND_CAP];
static unsigned snx_gfx_pass_n, snx_gfx_bind_n;
static int snx_gfx_pass_limited, snx_gfx_bind_limited;
static u64 snx_gfx_window = 1;
enum {
    SNX_GFX_SETUPS, SNX_GFX_DEPTH_ONLY, SNX_GFX_BINDINGS, SNX_GFX_NULL,
    SNX_GFX_SHADOW, SNX_GFX_NULL_SHADOW, SNX_GFX_INDEXED, SNX_GFX_SHADOW_COLOR,
    SNX_GFX_COUNT
};
static u64 snx_gfx_counts[SNX_GFX_COUNT];
int snx_gfx_diag_on;

void snx_gfx_init(void) {
    const char* e = getenv("SNX_GFX_DIAG");
    snx_gfx_diag_on = snx_perf_on && e && !strcmp(e, "1");
    if (snx_gfx_diag_on)
        LOG("SNX_GFX_META_V1 {\"shadows_enabled\":%d,\"pass_limit_per_window\":%d,\"binding_limit_per_window\":%d}\n",
            !!g_settings.shadows, SNX_GFX_PASS_CAP, SNX_GFX_BIND_CAP);
}

/* An exact bounded signature table: a full table stops detail, never counters. */
static int snx_gfx_first(SnxGfxKey* seen, unsigned* count, unsigned cap, int* limited,
                         const u64 key[SNX_GFX_KEY_WORDS], const char* kind) {
    if (*count == cap) {
        if (!*limited) {
            *limited = 1;
            LOG("SNX_GFX_LIMIT_V1 {\"window\":%llu,\"kind\":\"%s\",\"limit\":%u}\n",
                (unsigned long long)snx_gfx_window, kind, cap);
        }
        return 0;
    }
    for (unsigned i = 0; i < *count; i++)
        if (!memcmp(seen[i].key, key, sizeof seen[i].key)) return 0;
    memcpy(seen[(*count)++].key, key, sizeof seen[0].key);
    return 1;
}

/* Setup attempts, not proof of submitted geometry or nonempty depth pixels. */
static void snx_gfx_draw(const VkSh* vs, const VkSh* fs, Surf* const* rt, const Surf* zt,
                         u32 n, const u32* r) {
    if (!snx_gfx_diag_on) return;
    snx_gfx_counts[SNX_GFX_SETUPS]++;
    const Surf* color = NULL;
    for (u32 i = 0; i < n && i < 8; i++)
        if (rt[i]) { color = rt[i]; break; }
    if (!color && zt) snx_gfx_counts[SNX_GFX_DEPTH_ONLY]++;
    u64 key[SNX_GFX_KEY_WORDS] = {
        vs ? vs->hash : 0, fs ? fs->hash : 0,
        color ? color->gva : 0, zt ? zt->gva : 0,
        color ? color->w : 0, color ? color->h : 0,
        zt ? zt->w : 0, zt ? zt->h : 0,
        color ? (u32)color->f.vk : 0, zt ? (u32)zt->f.vk : 0,
        n, !!r[0x4B3], !!r[0x4BA], r[0x4C3]
    };
    if (!snx_gfx_first(snx_gfx_pass_seen, &snx_gfx_pass_n, SNX_GFX_PASS_CAP,
                       &snx_gfx_pass_limited, key, "draw_setup")) return;
    LOG("SNX_GFX_PASS_V1 {\"window\":%llu,\"frame\":%u,\"vs\":\"%016llx\",\"fs\":\"%016llx\","
        "\"color_slots\":%u,\"color\":\"%llx\",\"cw\":%u,\"ch\":%u,\"cf\":%u,"
        "\"depth\":\"%llx\",\"zw\":%u,\"zh\":%u,\"zf\":%u,"
        "\"depth_test\":%d,\"depth_write\":%d,\"depth_func\":%u}\n",
        (unsigned long long)snx_gfx_window, g_vk_present,
        (unsigned long long)key[0], (unsigned long long)key[1], n,
        (unsigned long long)key[2], color ? color->w : 0, color ? color->h : 0,
        color ? (u32)color->f.vk : 0, (unsigned long long)key[3], zt ? zt->w : 0,
        zt ? zt->h : 0, zt ? (u32)zt->f.vk : 0, !!r[0x4B3], !!r[0x4BA], r[0x4C3]);
}

/* Called before the existing null-view substitution. Indexed entries are CPU
 * descriptor preparations, not evidence that the shader sampled that element.
 * Handle zero is valid; bound tells us what actually happened to its view.
 */
static void snx_gfx_texture(const VkSh* s, int stage, int slot, const ShTex* st,
                            u32 handle, const u32* tic, const u32* tsc, const Surf* t,
                            VkImageViewType want, int num, VkImageView view, int indexed) {
    if (!snx_gfx_diag_on) return;
    int bound = view != VK_NULL_HANDLE;
    int manual = !!((s->si.tex_dc_color_mask >> slot) & 1);
    snx_gfx_counts[SNX_GFX_BINDINGS]++;
    snx_gfx_counts[SNX_GFX_NULL] += !bound;
    snx_gfx_counts[SNX_GFX_SHADOW] += !!st->shadow;
    snx_gfx_counts[SNX_GFX_NULL_SHADOW] += st->shadow && !bound;
    snx_gfx_counts[SNX_GFX_INDEXED] += !!indexed;
    snx_gfx_counts[SNX_GFX_SHADOW_COLOR] +=
        !indexed && st->shadow && !manual && bound && t && !t->f.depth;
    /* Keep detail for suspect binds, depth reads and non-2D resources (LUTs,
       environment maps). Ordinary valid 2D color binds only update counters. */
    if (bound && !st->shadow && t && !t->f.depth && want == VK_IMAGE_VIEW_TYPE_2D) return;
    u64 key[SNX_GFX_KEY_WORDS] = {
        s->hash, (u32)stage, (u32)slot, handle, (u32)want, (u32)num, (u32)bound,
        t ? t->gva : 0, t ? (u32)t->f.vk : 0, tic[0], tic[4], tsc[0],
        (u32)indexed, (u32)manual | (u32)st->shadow << 1
    };
    if (!snx_gfx_first(snx_gfx_bind_seen, &snx_gfx_bind_n, SNX_GFX_BIND_CAP,
                       &snx_gfx_bind_limited, key, "binding")) return;
    int actual = t && vk_tic_reads_stencil(tic) ? 1 : t && t->f.is_int ? (t->f.sint ? 2 : 1) : 0;
    const char* reason = bound ? "real_view" : !t ? "surface_unavailable"
                         : actual != num ? "numeric_kind" : "view_unavailable";
    LOG("SNX_GFX_BIND_V1 {\"window\":%llu,\"frame\":%u,\"shader\":\"%016llx\",\"stage\":%d,\"slot\":%d,"
        "\"indexed\":%d,\"handle\":\"%08x\",\"shadow\":%d,\"manual_compare\":%d,"
        "\"bound\":%d,\"reason\":\"%s\",\"want\":%u,\"num\":%d,"
        "\"surface\":\"%llx\",\"w\":%u,\"h\":%u,\"format\":%u,\"depth\":%d,"
        "\"tic0\":\"%08x\",\"tic2\":\"%08x\",\"tic4\":\"%08x\",\"tsc0\":\"%08x\"}\n",
        (unsigned long long)snx_gfx_window, g_vk_present, (unsigned long long)s->hash,
        stage, slot, !!indexed, handle,
        !!st->shadow, manual, bound, reason, (u32)want, num,
        (unsigned long long)(t ? t->gva : 0), t ? t->w : 0, t ? t->h : 0,
        t ? (u32)t->f.vk : 0, t ? !!t->f.depth : 0, tic[0], tic[2], tic[4], tsc[0]);
}

void snx_gfx_report(u64 window) {
    if (!snx_gfx_diag_on) return;
    LOG("SNX_GFX_V1 {\"window\":%llu,\"draw_setups\":%llu,\"depth_only_setups\":%llu,"
        "\"binding_events\":%llu,\"null_bindings\":%llu,\"shadow_bindings\":%llu,"
        "\"null_shadow_bindings\":%llu,\"indexed_entries\":%llu,\"shadow_color_views\":%llu}\n",
        (unsigned long long)window, (unsigned long long)snx_gfx_counts[SNX_GFX_SETUPS],
        (unsigned long long)snx_gfx_counts[SNX_GFX_DEPTH_ONLY],
        (unsigned long long)snx_gfx_counts[SNX_GFX_BINDINGS], (unsigned long long)snx_gfx_counts[SNX_GFX_NULL],
        (unsigned long long)snx_gfx_counts[SNX_GFX_SHADOW],
        (unsigned long long)snx_gfx_counts[SNX_GFX_NULL_SHADOW],
        (unsigned long long)snx_gfx_counts[SNX_GFX_INDEXED],
        (unsigned long long)snx_gfx_counts[SNX_GFX_SHADOW_COLOR]);
    memset(snx_gfx_counts, 0, sizeof snx_gfx_counts);
    snx_gfx_pass_n = snx_gfx_bind_n = 0;
    snx_gfx_pass_limited = snx_gfx_bind_limited = 0;
    snx_gfx_window = window + 1;
}
