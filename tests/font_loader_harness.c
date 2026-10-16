// Production shared-font decoder/loader, with only guest allocation replaced.
#include "../runtime/hle/pl.c"
#include <assert.h>

static void *allocations[64];
static unsigned nallocations;
void rt_fatal_trace(void) { abort(); }
void *hle_alloc(uint64_t size) {
    assert(nallocations < 64);
    void *p = calloc(1, size); assert(p);
    allocations[nallocations++] = p;
    return p;
}
size_t font_test_decode(uint8_t *data, size_t size) { return bfttf_decode(data, size); }
size_t font_test_load(const char *path, const uint8_t **out) {
    Font font = {0};
    if (!load_one(path, &font)) return 0;
    *out = (const uint8_t *)(uintptr_t)font.addr;
    return font.size;
}
size_t font_test_shared(unsigned type, const uint8_t **out) {
    const Font *font = font_for(type);
    *out = (const uint8_t *)(uintptr_t)font->addr;
    return font->size;
}
void font_test_reset(void) {
    pl_reset();
    for (unsigned i = 0; i < nallocations; ++i) free(allocations[i]);
    nallocations = 0;
}
