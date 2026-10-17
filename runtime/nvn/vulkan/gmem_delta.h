// Incremental updates for a completed, host-mapped GMEM snapshot.
// Pure C: no Vulkan dependencies; callers must guarantee the buffer is no
// longer referenced by in-flight submissions before modifying it.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    size_t first, end, copied;
} GmemDelta;

static inline GmemDelta gmem_delta_copy(uint8_t *mapped, uint8_t *shadow,
                                        const uint8_t *guest, size_t off, size_t size) {
    GmemDelta dirty = {SIZE_MAX, 0, 0};
    for (size_t pos = 0; pos < size;) {
        size_t n = size - pos < 4096 ? size - pos : 4096;
        size_t dest = off + pos;
        if (memcmp(shadow + dest, guest + pos, n) != 0) {
            memcpy(mapped + dest, guest + pos, n);
            memcpy(shadow + dest, guest + pos, n);
            if (dest < dirty.first) dirty.first = dest;
            if (dest + n > dirty.end) dirty.end = dest + n;
            dirty.copied += n;
        }
        pos += n;
    }
    return dirty;
}
