#pragma once
#include <stdbool.h>
#include <stdint.h>

// Shader CB index k >= 3 binds uniform-buffer slot k-3. For indirect
// global-memory addressing, every bound uniform range can be dereferenced.
// Graphics HLE also reads specific slots directly, independently of masks.
static inline bool las_vk_preflight_ubuf(unsigned stage, uint32_t cbuf_mask,
                                          bool indirect_gmem, unsigned slot) {
    if (slot >= 18) return false;
    if (indirect_gmem) return true;
    if (slot < 15 && (cbuf_mask & (UINT32_C(1) << (slot + 3)))) return true;
    // Runtime graphics helpers: widescreen, pot-glow, bottle, fade.
    if (stage == 0 && (slot == 0 || slot == 2 || slot == 3 || slot == 5)) return true;
    if (stage == 1 && slot == 0) return true;
    return false;
}

// Match the renderer's attribute-to-stream binding, including the constant
// ZERO_BINDING fallback for missing attributes (no guest range to resolve).
static inline uint32_t las_vk_preflight_vbuf_mask(uint32_t shader_attrs,
                                                  const uint32_t *attrib,
                                                  unsigned nattrib) {
    uint32_t used = 0;
    if (nattrib > 16) nattrib = 16;
    for (unsigned i = 0; i < nattrib; ++i) {
        if (!(shader_attrs & (UINT32_C(1) << i))) continue;
        const uint32_t a = attrib[i];
        const unsigned fmt = a & 0xffu, stream = (a >> 8) & 31u;
        if (fmt && stream < 16) used |= UINT32_C(1) << stream;
    }
    return used;
}
