// Run in Termux or on a host:
// clang -std=c11 -O2 -Wall -Wextra -Werror tests/test_touch_axes.c -o /tmp/touch_axes && /tmp/touch_axes
#include <assert.h>
#include <stdio.h>
#include "../runtime/hle/touch_axes.h"

int main(void) {
    LasTouchAxes axes = {0};
    int32_t x = -1, y = -1;
    las_touch_axes_get(&axes, 0, &x, &y);
    assert(x == 0 && y == 0);
    las_touch_axes_set(&axes, 0, 15555, -30000);
    las_touch_axes_get(&axes, 0, &x, &y);
    assert(x == 15555 && y == -30000);
    las_touch_axes_get(&axes, 1, &x, &y);
    assert(x == 0 && y == 0); // independent right stick
    las_touch_axes_set(&axes, 1, 70000, -70000);
    las_touch_axes_get(&axes, 1, &x, &y);
    assert(x == 32767 && y == -32767); // signed Switch HID range
    las_touch_axes_set(&axes, 7, 111, 222);
    las_touch_axes_get(&axes, 1, &x, &y);
    assert(x == 32767 && y == -32767); // invalid stick cannot corrupt either axis
    las_touch_axes_set(&axes, 0, 0, 0);
    las_touch_axes_get(&axes, 0, &x, &y);
    assert(x == 0 && y == 0); // released to center
    las_touch_axes_get(&axes, 1, &x, &y);
    assert(x == 32767 && y == -32767); // releasing left doesn't release right
    las_touch_axes_set(&axes, 1, 0, 0);
    las_touch_axes_get(&axes, 1, &x, &y);
    assert(x == 0 && y == 0);
    puts("TEST_TOUCH_AXES_PASS");
    return 0;
}
