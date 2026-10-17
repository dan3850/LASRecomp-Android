// clang -std=c11 -O1 -g -Wall -Wextra -Werror
// -fsanitize=address,undefined tests/test_gmem_atlas.c -o /tmp/test_gmem_atlas
#include "../runtime/nvn/vulkan/gmem_atlas_regions.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(void) {
    uint8_t guest[8192] = {0}, shadow[4096] = {0};
    GmemAtlasRegion rr[4] = {{1024, 768, 256}, {2048, 512, 1280}};
    for (size_t i = 0; i < sizeof guest; ++i) guest[i] = (uint8_t)(i * 17u + 3u);
    memcpy(shadow + 256, guest + 1024, 768);
    memcpy(shadow + 1280, guest + 2048, 512);
    uint32_t offset = UINT32_MAX;
    assert(gmem_atlas_region_find(rr, 2, shadow, sizeof shadow, guest, sizeof guest, 1024, 768, &offset) && offset == 256);
    assert(gmem_atlas_region_find(rr, 2, shadow, sizeof shadow, guest, sizeof guest, 1280, 256, &offset) && offset == 512);
    assert(gmem_atlas_region_find(rr, 2, shadow, sizeof shadow, guest, sizeof guest, 2048, 512, &offset) && offset == 1280);
    offset = UINT32_MAX;
    assert(!gmem_atlas_region_find(rr, 2, shadow, sizeof shadow, guest, sizeof guest, 1280, 800, &offset));
    assert(offset == UINT32_MAX);
    guest[1300] ^= 1;
    assert(!gmem_atlas_region_find(rr, 2, shadow, sizeof shadow, guest, sizeof guest, 1280, 256, &offset));
    assert(gmem_atlas_region_find(rr, 2, shadow, sizeof shadow, guest, sizeof guest, 1024, 256, &offset) && offset == 256);
    guest[1300] ^= 1;
    GmemAtlasRegion after = {1280, 256, 1800};
    rr[2] = after;
    memcpy(shadow + 1800, guest + 1280, 256);
    assert(gmem_atlas_region_find(rr, 3, shadow, sizeof shadow, guest, sizeof guest, 1280, 256, &offset) && offset == 1800);
    guest[1300] ^= 1;
    assert(!gmem_atlas_region_find(rr, 3, shadow, sizeof shadow, guest, sizeof guest, 1280, 256, &offset));
    guest[1300] ^= 1;
    assert(gmem_atlas_region_find(rr, 3, shadow, sizeof shadow, guest, sizeof guest, 1280, 256, &offset) && offset == 1800);
    // Reject out-of-range and unaligned queries; failure never changes offset.
    offset = UINT32_MAX;
    assert(!gmem_atlas_region_find(rr, 3, shadow, sizeof shadow, guest, sizeof guest, 8192, 4, &offset));
    assert(!gmem_atlas_region_find(rr, 3, shadow, sizeof shadow, guest, sizeof guest, 1025, 256, &offset));
    assert(offset == UINT32_MAX);
    puts("TEST_GMEM_ATLAS_PASS");
    return 0;
}
