// Real analog axis normalization for Android touch input.
// Vulkan-free, and safe to test on a host without the game code.
#pragma once
#include <stdint.h>
#include <math.h>

static inline int32_t las_touch_axis(float value) {
    if (!isfinite(value)) value = 0;
    if (value > 1.f) value = 1.f;
    if (value < -1.f) value = -1.f;
    return (int32_t)(value * 32767.f);
}
