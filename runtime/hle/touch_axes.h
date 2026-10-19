// Android touch analog axes: one atomic snapshot per stick.
// No SDL, Vulkan or JNI dependency. Input thread always sees both coordinates
// from the same touch event, including centered/reset values.
#pragma once
#include <stdatomic.h>
#include <stdint.h>

typedef struct {
    _Atomic uint64_t xy[2];
} LasTouchAxes;

static inline int32_t las_touch_clamp(int32_t v) {
    if (v > 32767) return 32767;
    if (v < -32767) return -32767;
    return v;
}

static inline void las_touch_axes_set(LasTouchAxes *state, int stick,
                                      int32_t x, int32_t y) {
    if (!state || (unsigned)stick >= 2) return;
    uint64_t packed = (uint32_t)las_touch_clamp(x) |
                      ((uint64_t)(uint32_t)las_touch_clamp(y) << 32);
    atomic_store_explicit(&state->xy[stick], packed, memory_order_relaxed);
}

static inline void las_touch_axes_get(const LasTouchAxes *state, int stick,
                                      int32_t *x, int32_t *y) {
    if (!state || !x || !y || (unsigned)stick >= 2) return;
    uint64_t packed = atomic_load_explicit(&state->xy[stick], memory_order_relaxed);
    // Unsigned -> signed conversion is defined by the target AArch64 ABI.
    *x = (int32_t)(uint32_t)packed;
    *y = (int32_t)(uint32_t)(packed >> 32);
}
