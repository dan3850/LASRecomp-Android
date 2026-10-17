// Build: clang -std=c11 -O2 -Wall -Wextra -Werror
// tests/test_vk_60_recovery.c -o /tmp/test_vk_60_recovery
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/recovery60_policy.h"
int main(void) {
 LasRecovery r={0};
 for(int i=0;i<1000;i++) assert(!las_recovery_frame(&r,16666667,8000));
 assert(!las_recovery_pulse(&r)); // sustained natural 60fps: untouched
 for(int i=0;i<200;i++) assert(!las_recovery_frame(&r,33333333,15000));
 assert(!las_recovery_pulse(&r)); // genuinely GPU-bound: untouched
 for(int i=0;i<89;i++) assert(!las_recovery_frame(&r,33333333,10000));
 assert(!las_recovery_pulse(&r));
 assert(las_recovery_frame(&r,33333333,10000)==1);
 assert(las_recovery_pulse(&r));
 for(int i=0;i<44;i++) assert(!las_recovery_frame(&r,16666667,10000));
 assert(las_recovery_pulse(&r));
 assert(las_recovery_frame(&r,16666667,10000)==-1);
 assert(!las_recovery_pulse(&r));
 for(int i=0;i<600;i++) assert(!las_recovery_frame(&r,33333333,10000));
 assert(!las_recovery_pulse(&r)); // retry bounded by cooldown
 for(int i=0;i<90;i++) las_recovery_frame(&r,33333333,10000);
 assert(las_recovery_pulse(&r));
 assert(las_recovery_frame(&r,33333333,20000)==-1); // real GPU overload aborts
 assert(!las_recovery_pulse(&r));
 las_recovery_reset(&r);
 for(int i=0;i<90;i++) las_recovery_frame(&r,33333333,10000);
 assert(las_recovery_pulse(&r));
 for(int i=0;i<179;i++) las_recovery_frame(&r,33333333,10000);
 assert(las_recovery_frame(&r,33333333,10000)==-1); // no recovery => give up
 assert(!las_recovery_pulse(&r));
 las_recovery_reset(&r);
 for(int i=0;i<45;i++) las_recovery_frame(&r,33333333,10000);
 las_recovery_frame(&r,90000000,10000);
 for(int i=0;i<45;i++) las_recovery_frame(&r,33333333,10000);
 assert(!las_recovery_pulse(&r)); // interrupted streak must restart
 puts("TEST_VK_60_RECOVERY_PASS");
 return 0;
}
