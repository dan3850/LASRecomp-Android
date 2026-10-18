// Termux/host: clang -std=c11 -O2 -Wall -Wextra -Werror tests/test_vk_preflight_policy.c -o /tmp/test_vk_preflight_policy && /tmp/test_vk_preflight_policy
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/preflight_policy.h"
int main(void) {
    assert(!las_vk_preflight_ubuf(5, 0, false, 0));
    assert(las_vk_preflight_ubuf(5, UINT32_C(1) << 3, false, 0));
    assert(las_vk_preflight_ubuf(5, UINT32_C(1) << 17, false, 14));
    assert(!las_vk_preflight_ubuf(5, UINT32_C(1) << 17, false, 15));
    assert(las_vk_preflight_ubuf(5, 0, true, 17));
    assert(las_vk_preflight_ubuf(0, 0, false, 0));
    assert(las_vk_preflight_ubuf(0, 0, false, 2));
    assert(las_vk_preflight_ubuf(0, 0, false, 3));
    assert(las_vk_preflight_ubuf(0, 0, false, 5));
    assert(las_vk_preflight_ubuf(1, 0, false, 0));
    assert(!las_vk_preflight_ubuf(1, 0, false, 5));
    uint32_t a[16] = {0};
    a[0] = 0x2eu | (3u << 8);
    a[1] = 0x2eu | (7u << 8);
    a[2] = 0x2eu | (25u << 8);
    a[3] = 0x0u | (9u << 8);
    assert(las_vk_preflight_vbuf_mask(0xf, a, 4) == ((1u << 3) | (1u << 7)));
    assert(las_vk_preflight_vbuf_mask(1, a, 4) == (1u << 3));
    assert(las_vk_preflight_vbuf_mask(0xffff, a, 0) == 0);
    puts("TEST_VK_PREFLIGHT_POLICY_PASS");
}
