// Standalone Vulkan-free tests: clang -std=c11 -Wall -Wextra -Werror
// -fsanitize=address,undefined tests/test_resident_regions.c -o /tmp/regions && /tmp/regions
#include "../runtime/nvn/vulkan/resident_regions.h"
#include <assert.h>
#include <stdlib.h>

static void test_dirty_regions(void) {
    const size_t n = 5 * 4096 + 4;
    uint8_t *a = calloc(1, n), *b = calloc(1, n);
    ResidentRegion r[8];
    assert(a && b);
    assert(resident_dirty_regions(a,b,n,4096,r,8) == 0);
    b[33] = 5;
    assert(resident_dirty_regions(a,b,n,4096,r,8) == 1);
    assert(r[0].offset == 0 && r[0].size == 4096);
    b[4096] = 1;
    assert(resident_dirty_regions(a,b,n,4096,r,8) == 1);
    assert(r[0].size == 8192); // adjacent pages merge
    b[4*4096+20] = 1;
    assert(resident_dirty_regions(a,b,n,4096,r,8) == 2);
    assert(r[1].offset == 4*4096 && r[1].size == 4096);
    b[n-1] = 1;
    assert(resident_dirty_regions(a,b,n,4096,r,8) == 2);
    assert(r[1].size == 4100); // 4-byte tail correctly padded
    assert(resident_dirty_regions(a,b,n,4096,r,1) == SIZE_MAX);
    assert(resident_dirty_regions(a,b,n,3,r,8) == SIZE_MAX);
    b[33] = b[4096] = b[4*4096+20] = b[n-1] = 0;
    assert(resident_dirty_regions(a,b,n,4096,r,8) == 0);
    free(a); free(b);
}
static void test_versions(void) {
    assert(resident_rewrite_safe(0,0));
    assert(!resident_rewrite_safe(25,24));
    assert(!resident_rewrite_safe(25,0));
    assert(resident_rewrite_safe(25,25));
    assert(resident_rewrite_safe(24,25));
}
// Reconstruct changed images from the calculated GPU copy regions.
// Checks both sparse changes and the full-copy fallback deterministically.
static void test_reconstruct(void) {
    enum { N = 20 * 4096 + 4 };
    uint8_t *before = calloc(1, N), *after = calloc(1, N);
    uint8_t *rebuilt = calloc(1, N);
    assert(before && after && rebuilt);
    unsigned seed = 0x7129u;
    for (int test = 0; test < 256; ++test) {
        for (int i = 0; i < 150; ++i) {
            seed = seed * 1664525u + 1013904223u;
            size_t at = seed % N;
            after[at] ^= (uint8_t)(seed >> 24);
        }
        ResidentRegion dirty[8];
        size_t n = resident_dirty_regions(before, after, N, 4096, dirty, 8);
        memcpy(rebuilt, before, N);
        if (n == SIZE_MAX) memcpy(rebuilt, after, N);
        else for (size_t i = 0; i < n; ++i)
            memcpy(rebuilt + dirty[i].offset, after + dirty[i].offset, dirty[i].size);
        assert(!memcmp(rebuilt, after, N));
        memcpy(before, after, N);
    }
    free(before); free(after); free(rebuilt);
}
int main(void) { test_dirty_regions(); test_versions(); test_reconstruct(); return 0; }
