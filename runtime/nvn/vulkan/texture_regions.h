// CPU-side dirty-row planning for Vulkan image subresource updates.
// Pure C, no driver dependencies; works for packed uncompressed texels.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct { uint32_t first, count; } NativeTexRows;

// Compare canonical tightly packed shadow against source with guest pitch.
// Merge contiguous modified rows into copy rectangles. Return SIZE_MAX when
// there are too many runs; caller must issue a full-subresource copy.
// Never infer unchanged rows from a hash or a frame number.
static inline size_t native_tex_dirty_rows(const uint8_t *shadow,
       const uint8_t *source, size_t bytes_per_row, size_t pitch,
       uint32_t height, NativeTexRows *runs, size_t capacity,
       size_t *changed_bytes) {
    if (!shadow || !source || !bytes_per_row || pitch < bytes_per_row)
        return SIZE_MAX;
    size_t n = 0, total = 0;
    for (uint32_t y = 0; y < height; ++y) {
        const uint8_t *old_row = shadow + (size_t)y * bytes_per_row;
        const uint8_t *new_row = source + (size_t)y * pitch;
        if (!memcmp(old_row, new_row, bytes_per_row)) continue;
        total += bytes_per_row;
        if (n && runs[n - 1].first + runs[n - 1].count == y) {
            ++runs[n - 1].count;
        } else {
            if (n == capacity) return SIZE_MAX;
            runs[n++] = (NativeTexRows){y, 1};
        }
    }
    if (changed_bytes) *changed_bytes = total;
    return n;
}
