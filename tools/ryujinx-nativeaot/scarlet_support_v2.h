/* SPDX-License-Identifier: MIT
 * SupportBuffer's std140 offsets from the pinned Ryujinx SupportBuffer.cs:
 * alpha=0, is_bgra=16, viewport_inverse=144, viewport_size=160,
 * frag_scale_count=176, render_scale[73]=192, tfe_offset=1360, count=1376.
 */
#define SNX_RYU_SUPPORT_SIZE 1392
static int snx_ryu_support(const float scales[65], u32 alpha_reference, VkBuffer* buffer, u64* offset) {
    static u64 submit = ~0ull, cached_offset;
    static VkBuffer cached_buffer;
    static u8 cached[SNX_RYU_SUPPORT_SIZE];
    u8 data[SNX_RYU_SUPPORT_SIZE] = {0};
    memcpy(data, &alpha_reference, 4);
    for (unsigned i = 0; i < 73; i++) {
        float scale = i < 65 ? scales[i] : 1.0f;
        memcpy(data + 192 + i * 16, &scale, 4);
    }
    if (submit != vk_submit_number() || memcmp(data, cached, sizeof data)) {
        u8* p = vk_stage(sizeof data, vk_stage_align(), &cached_buffer, &cached_offset);
        if (!p) return 0;
        memcpy(p, data, sizeof data); memcpy(cached, data, sizeof data);
        submit = vk_submit_number();
    }
    *buffer = cached_buffer; *offset = cached_offset;
    return 1;
}
