// clang -std=c11 -O2 -Wall -Wextra -Werror
// tests/test_vk_counter_ready.c -o /tmp/test_vk_counter_ready && /tmp/test_vk_counter_ready
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/counter_ready.h"
int main(void) {
    uint64_t last = 0;
    assert(!vk_counter_completion_advanced(0, &last));
    assert(vk_counter_completion_advanced(7, &last) && last == 7);
    assert(!vk_counter_completion_advanced(7, &last));
    assert(!vk_counter_completion_advanced(6, &last));
    assert(vk_counter_completion_advanced(9, &last) && last == 9);
    assert(!vk_counter_completion_advanced(10, NULL));
    // Switch counter clock = 614.4 MHz; each tick = 625/384 ns.
    const double ns = 625.0 / 384.0;
    assert(vk_counter_host_overstates_gpu(0, 15000000, 9.0, ns));
    assert(!vk_counter_host_overstates_gpu(0, 5000000, 9.0, ns));
    assert(!vk_counter_host_overstates_gpu(0, 15000000, 19.0, ns));
    assert(!vk_counter_host_overstates_gpu(15000000, 0, 9.0, ns));
    puts("TEST_VK_COUNTER_READY_PASS");
    return 0;
}
