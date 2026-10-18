#include "../runtime/nvn/vulkan/worker_budget.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    // Preserve the original desktop worker policy (logical CPUs minus four, clamped to 4..16).
    assert(las_vk_worker_count(1, false, NULL) == 4);
    assert(las_vk_worker_count(8, false, NULL) == 4);
    assert(las_vk_worker_count(16, false, NULL) == 12);
    assert(las_vk_worker_count(64, false, NULL) == 16);
    // Android uses three by default, regardless of its reported CPU count.
    assert(las_vk_worker_count(0, true, NULL) == 3);
    assert(las_vk_worker_count(8, true, NULL) == 3);
    assert(las_vk_worker_count(16, true, "") == 3);
    // Allow reproducible A/B tests and return to the old Android minimum (4).
    assert(las_vk_worker_count(8, true, "4") == 4);
    assert(las_vk_worker_count(8, true, "1") == 1);
    assert(las_vk_worker_count(8, true, "16") == 16);
    assert(las_vk_worker_count(16, false, "3") == 3);
    // Bad values cannot start zero workers or accidentally spawn huge numbers.
    assert(las_vk_worker_count(8, true, "0") == 3);
    assert(las_vk_worker_count(8, true, "17") == 3);
    assert(las_vk_worker_count(8, true, "999999999999999999999") == 3);
    assert(las_vk_worker_count(8, true, "4x") == 3);
    assert(las_vk_worker_count(8, true, "-2") == 3);
    assert(las_vk_worker_count(8, true, " 4") == 3);
    assert(las_vk_worker_count(8, false, "0") == 4);
    puts("vk worker budget: all checks PASS");
    return 0;
}
