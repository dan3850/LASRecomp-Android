// Host/Termux: clang -std=c11 -Wall -Wextra -Werror tests/test_vk_present_wait.c -o /tmp/present-wait-test && /tmp/present-wait-test
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/present_wait_stats.h"

int main(void) {
    LasPresentWaitStats s = {0};
    assert(!las_present_wait_due(&s, UINT64_C(2000000000)));
    las_present_wait_record(&s, UINT64_C(10000000000), UINT64_C(1000000), UINT64_C(31000000));
    assert(s.frames == 1 && s.slot_total_ns == 1000000);
    assert(s.acquire_over_16ms == 1 && s.slot_over_16ms == 0);
    assert(!las_present_wait_due(&s, UINT64_C(11999999999)));
    las_present_wait_record(&s, UINT64_C(12000000000), UINT64_C(17500000), UINT64_C(2000000));
    assert(s.frames == 2 && s.slot_total_ns == UINT64_C(18500000));
    assert(s.acquire_total_ns == UINT64_C(33000000));
    assert(s.slot_peak_ns == UINT64_C(17500000));
    assert(s.acquire_peak_ns == UINT64_C(31000000));
    assert(s.slot_over_16ms == 1 && s.acquire_over_16ms == 1);
    assert(las_present_wait_due(&s, UINT64_C(12000000000)));
    s = (LasPresentWaitStats){0};
    las_present_wait_record(&s, UINT64_C(13000000000), 0, 0);
    assert(s.slot_peak_ns == 0 && s.acquire_peak_ns == 0);
    assert(!las_present_wait_due(&s, UINT64_C(13000000000)));
    puts("TEST_VK_PRESENT_WAIT_PASS");
}
