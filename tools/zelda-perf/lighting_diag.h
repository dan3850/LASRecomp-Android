/* SPDX-License-Identifier: MIT
 * Passive detailed-mode evidence; included after gfx_diag.h under vk_lock.
 * No allocations, resource resolution, GPU commands or image reads. A state
 * family records its first target example, not every draw or a visible pixel.
 */
enum { SNX_LIGHT_STATE_CAP = 64, SNX_LIGHT_RT_CAP = 64 };
static const u32 snx_light_regs[] = {
    0x3e4, 0x4b3, 0x4ba, 0x4c3, 0x4bb, 0x4c4, 0x4c5, 0x4b9,
    0x4d0, 0x4d1, 0x4d2, 0x4d3, 0x4d4, 0x4d6, 0x4c7, 0x4c8, 0x4c9, 0x4ca,
    0x4e0, 0x4e4, 0x4e5, 0x4e6, 0x4e7, 0x565, 0x569, 0x3d5, 0x3d6, 0x3d7,
    0x35f, 0x64f, 0x4eb, 0x286, 0x280, 0x281, 0x282, 0x283, 0x284, 0x285,
    0x55b, 0x56f, 0x61f, 0x56e, 0x646, 0x647, 0x648, 0x380, 0x381, 0x382
};
typedef struct {
    u64 vs, fs;
    u32 slot, ncolor, color_format, depth_format, fragment_outputs;
    u32 regs[sizeof snx_light_regs / sizeof *snx_light_regs];
    u32 blend[8], target_blend[8], write_mask, depth_bits[2];
} SnxLightState;
static SnxLightState snx_light_seen[SNX_LIGHT_STATE_CAP];
static SnxGfxKey snx_light_rt_seen[SNX_LIGHT_RT_CAP];
static unsigned snx_light_n, snx_light_rt_n;
static int snx_light_limited, snx_light_rt_limited;
static u64 snx_light_window = 1, snx_light_attempts, snx_light_rt_attempts, snx_light_line_refused;

void snx_lighting_init(void) {
    if (!snx_gfx_diag_on) return;
    LOG("SNX_LIGHT_META_V1 {\"diagnostic_only\":1,\"state_limit_per_window\":64,"
        "\"color_rt_limit_per_window\":64,\"line_bytes\":2048,"
        "\"scope\":\"state_family_first_target\",\"color_slot_scope\":\"first_bound\","
        "\"extra_gpu_work\":0}\n");
}

static void snx_lighting_state(const VkSh* vs, const VkSh* fs, Surf* const* rt,
                                const Surf* zt, const PipeKey* pipe, const u32* r) {
    if (!snx_gfx_diag_on) return;
    snx_light_attempts++;
    if (snx_light_n == SNX_LIGHT_STATE_CAP) {
        if (!snx_light_limited) {
            snx_light_limited = 1;
            LOG("SNX_LIGHT_LIMIT_V1 {\"window\":%llu,\"kind\":\"raster_state\",\"limit\":64}\n",
                (unsigned long long)snx_light_window);
        }
        return;
    }
    u32 slot = 0;
    while (slot < pipe->ncolor && slot < 8 && !rt[slot]) slot++;
    const Surf* color = slot < pipe->ncolor && slot < 8 ? rt[slot] : NULL;
    if (!color) slot = 0;
    SnxLightState key;
    memset(&key, 0, sizeof key);
    key.vs = vs ? vs->hash : 0; key.fs = fs ? fs->hash : 0;
    key.slot = slot; key.ncolor = pipe->ncolor;
    key.color_format = color ? pipe->color[slot] : 0; key.depth_format = pipe->depth;
    key.fragment_outputs = fs ? fs->si.sph[18] : 0;
    for (unsigned i = 0; i < sizeof snx_light_regs / sizeof *snx_light_regs; i++) key.regs[i] = r[snx_light_regs[i]];
    memcpy(key.blend, &pipe->blend[slot], sizeof key.blend);
    memcpy(key.target_blend, &r[0x780 + slot * 8], sizeof key.target_blend);
    key.write_mask = r[r[0x3e4] ? 0x680 : 0x680 + slot];
    VkViewport vp = vk_render_viewport(r); /* existing pure state conversion, no Vulkan command */
    memcpy(&key.depth_bits[0], &vp.minDepth, 4); memcpy(&key.depth_bits[1], &vp.maxDepth, 4);
    for (unsigned i = 0; i < snx_light_n; i++) if (!memcmp(&snx_light_seen[i], &key, sizeof key)) return;
    snx_light_seen[snx_light_n++] = key;
    char line[2048];
    int used = snprintf(line, sizeof line,
        "SNX_LIGHT_STATE_V1 {\"window\":%llu,\"frame\":%u,\"vs\":\"%016llx\",\"fs\":\"%016llx\","
        "\"color_slot\":%u,\"color_slots\":%u,\"color\":\"%llx\",\"cw\":%u,\"ch\":%u,"
        "\"cf\":%u,\"depth\":\"%llx\",\"zf\":%u,\"fragment_outputs\":%u,"
        "\"viewport_depth_bits\":[\"%08x\",\"%08x\"],\"blend_effective\":[",
        (unsigned long long)snx_light_window, g_vk_present,
        (unsigned long long)key.vs, (unsigned long long)key.fs, slot, key.ncolor,
        (unsigned long long)(color ? color->gva : 0), color ? color->w : 0, color ? color->h : 0,
        key.color_format, (unsigned long long)(zt ? zt->gva : 0), key.depth_format, key.fragment_outputs,
        key.depth_bits[0], key.depth_bits[1]);
    if (used < 0 || (size_t)used >= sizeof line) goto refused;
#define SNX_LIGHT_APPEND(...) do { \
    int add = snprintf(line + used, sizeof line - (size_t)used, __VA_ARGS__); \
    if (add < 0 || (size_t)add >= sizeof line - (size_t)used) goto refused; \
    used += add; \
} while (0)
    for (unsigned i = 0; i < 8; i++) SNX_LIGHT_APPEND("%s%u", i ? "," : "", key.blend[i]);
    SNX_LIGHT_APPEND("],\"target_blend_words\":[");
    for (unsigned i = 0; i < 8; i++) SNX_LIGHT_APPEND("%s\"%08x\"", i ? "," : "", key.target_blend[i]);
    SNX_LIGHT_APPEND("],\"write_mask\":\"%08x\",\"regs\":{", key.write_mask);
    for (unsigned i = 0; i < sizeof snx_light_regs / sizeof *snx_light_regs; i++)
        SNX_LIGHT_APPEND("%s\"%03x\":\"%08x\"", i ? "," : "", snx_light_regs[i], key.regs[i]);
    SNX_LIGHT_APPEND("}}");
    LOG("%s\n", line);
    return;
refused:
    snx_light_line_refused++;
#undef SNX_LIGHT_APPEND
}

static void snx_lighting_texture(const VkSh* shader, int stage, int slot, const ShTex* st,
                                  u32 handle, const u32* tic, const u32* tsc, const Surf* t,
                                  VkImageViewType want, int num, VkImageView view) {
    if (!snx_gfx_diag_on || !t || !t->is_rt || t->f.depth || st->shadow ||
        want != VK_IMAGE_VIEW_TYPE_2D || view == VK_NULL_HANDLE) return;
    snx_light_rt_attempts++;
    u64 key[SNX_GFX_KEY_WORDS] = {shader->hash, (u32)stage, (u32)slot, handle, t->gva,
        (u32)t->f.vk, t->w, t->h, tic[0], tic[4], tsc[0], tsc[1], (u32)want, (u32)num};
    if (!snx_gfx_first(snx_light_rt_seen, &snx_light_rt_n, SNX_LIGHT_RT_CAP,
                       &snx_light_rt_limited, key, "lighting_color_rt")) return;
    LOG("SNX_LIGHT_RT_V1 {\"window\":%llu,\"frame\":%u,\"shader\":\"%016llx\",\"stage\":%d,"
        "\"slot\":%d,\"handle\":\"%08x\",\"surface\":\"%llx\",\"w\":%u,\"h\":%u,"
        "\"sw\":%u,\"sh\":%u,\"format\":%u,\"want\":%u,\"num\":%d,\"tic\":["
        "%u,%u,%u,%u,%u,%u,%u,%u],\"tsc\":[%u,%u,%u,%u,%u,%u,%u,%u]}\n",
        (unsigned long long)snx_light_window, g_vk_present, (unsigned long long)shader->hash,
        stage, slot, handle, (unsigned long long)t->gva, t->w, t->h, t->sw, t->sh,
        (u32)t->f.vk, (u32)want, num, tic[0],tic[1],tic[2],tic[3],tic[4],tic[5],tic[6],tic[7],
        tsc[0],tsc[1],tsc[2],tsc[3],tsc[4],tsc[5],tsc[6],tsc[7]);
}

void snx_lighting_report(u64 window) {
    if (!snx_gfx_diag_on) return;
    LOG("SNX_LIGHT_V1 {\"window\":%llu,\"state_attempts\":%llu,\"state_records\":%u,"
        "\"color_rt_bind_attempts\":%llu,\"color_rt_records\":%u,\"state_limited\":%d,"
        "\"color_rt_limited\":%d,\"line_refused\":%llu}\n",
        (unsigned long long)window, (unsigned long long)snx_light_attempts, snx_light_n,
        (unsigned long long)snx_light_rt_attempts, snx_light_rt_n, snx_light_limited,
        snx_light_rt_limited, (unsigned long long)snx_light_line_refused);
    snx_light_n = snx_light_rt_n = 0;
    snx_light_limited = snx_light_rt_limited = 0;
    snx_light_attempts = snx_light_rt_attempts = snx_light_line_refused = 0;
    snx_light_window = window + 1;
}
