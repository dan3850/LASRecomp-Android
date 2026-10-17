// clang -O1 -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_texture_regions.c -o /tmp/test_tex_regions && /tmp/test_tex_regions
#include "../runtime/nvn/vulkan/texture_regions.h"
#include <assert.h>
#include <stdlib.h>

static void basic(void) {
    uint8_t shadow[6 * 4] = {0};
    uint8_t src[6 * 7] = {0};
    NativeTexRows rect[6];
    size_t dirty = 0;
    assert(native_tex_dirty_rows(shadow, src, 4, 7, 6, rect, 6, &dirty) == 0);
    src[7 * 1] = 1;
    src[7 * 2] = 2;
    src[7 * 4 + 3] = 3;
    assert(native_tex_dirty_rows(shadow, src, 4, 7, 6, rect, 6, &dirty) == 2);
    assert(dirty == 12 && rect[0].first == 1 && rect[0].count == 2 &&
           rect[1].first == 4 && rect[1].count == 1);
    assert(native_tex_dirty_rows(shadow, src, 4, 7, 6, rect, 1, NULL) == SIZE_MAX);
    assert(native_tex_dirty_rows(shadow, src, 4, 3, 6, rect, 6, NULL) == SIZE_MAX);
}
static void randomized(void) {
    enum { H = 99, W = 17, PITCH = 29 };
    uint8_t old[H * W] = {0}, source[H * PITCH] = {0}, copy[H * W] = {0};
    NativeTexRows r[32];
    unsigned seed = 1234567;
    for (int t = 0; t < 1000; ++t) {
        for (int i = 0; i < 9; ++i) {
            seed = seed * 1664525u + 1013904223u;
            size_t y = seed % H;
            seed = seed * 1664525u + 1013904223u;
            size_t x = seed % W;
            source[y * PITCH + x] ^= (uint8_t)(seed >> 24);
        }
        size_t changed = 0;
        size_t n = native_tex_dirty_rows(old, source, W, PITCH, H, r, 32, &changed);
        memcpy(copy, old, sizeof copy);
        if (n == SIZE_MAX) {
            for (unsigned y = 0; y < H; ++y)
                memcpy(copy + y * W, source + y * PITCH, W);
        } else {
            size_t counted = 0;
            for (size_t i = 0; i < n; ++i) {
                for (unsigned y = r[i].first; y < r[i].first + r[i].count; ++y) {
                    memcpy(copy + (size_t)y * W, source + (size_t)y * PITCH, W);
                    counted += W;
                }
            }
            assert(counted == changed);
        }
        for (unsigned y = 0; y < H; ++y)
            memcpy(old + y * W, source + y * PITCH, W);
        assert(!memcmp(copy, old, sizeof old));
    }
}
int main(void) { basic(); randomized(); return 0; }
