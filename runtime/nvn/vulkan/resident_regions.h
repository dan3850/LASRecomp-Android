// Pure C policy for choosing incremental ranges in persistent GPU buffers.
// Does not know about Vulkan or guest memory; unit-tested in tests/.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

typedef struct { size_t offset, size; } ResidentRegion;

// A GPU buffer may be rewritten only after *all* submissions that read it
// have completed. The pending submission has not signalled yet.
static inline bool resident_rewrite_safe(uint64_t last_use, uint64_t completed) {
    return last_use <= completed;
}

// Compare 4-KiB chunks, merge adjacent dirty chunks, and bound the number of
// copies submitted to the GPU. Inputs include their zero-padded final bytes,
// so offsets and lengths are multiples of four as VkBufferCopy requires.
// SIZE_MAX means too many disjoint changes: use one full-size upload.
static inline size_t resident_dirty_regions(const uint8_t *old_bytes,
        const uint8_t *new_bytes, size_t size, size_t page,
        ResidentRegion *out, size_t capacity) {
    if (!page || (page & 3) || (size & 3)) return SIZE_MAX;
    size_t n = 0;
    for (size_t off = 0; off < size;) {
        size_t len = size - off < page ? size - off : page;
        if (memcmp(old_bytes + off, new_bytes + off, len)) {
            if (n && out[n-1].offset + out[n-1].size == off)
                out[n-1].size += len;
            else {
                if (n == capacity) return SIZE_MAX;
                out[n++] = (ResidentRegion){off, len};
            }
        }
        off += len;
    }
    return n;
}
