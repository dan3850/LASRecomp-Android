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
int main(void) { test_dirty_regions(); test_versions(); return 0; }
