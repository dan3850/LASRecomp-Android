// Host/Termux regression: real 16-bit Switch analog values and safe clamps.
// clang -std=c11 -O2 -Wall -Wextra -Werror tests/test_android_touch_axis.c -lm -o /tmp/test_touch && /tmp/test_touch
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "../runtime/hle/touch_axis_policy.h"

int main(void) {
    assert(las_touch_axis(0.f) == 0);
    assert(las_touch_axis(1.f) == 32767);
    assert(las_touch_axis(-1.f) == -32767);
    assert(las_touch_axis(2.f) == 32767);
    assert(las_touch_axis(-2.f) == -32767);
    assert(las_touch_axis(0.5f) >= 16383 && las_touch_axis(0.5f) <= 16384);
    assert(las_touch_axis(NAN) == 0);
    assert(las_touch_axis(INFINITY) == 0);
    assert(las_touch_axis(-INFINITY) == 0);
    // Canvas up (negative Y) maps to positive Switch axis.
    assert(las_touch_axis(-(-1.f)) == 32767);
    puts("ANDROID_TOUCH_ANALOG_PASS");
    return 0;
}
