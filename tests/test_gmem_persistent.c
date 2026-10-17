// Compile: clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_gmem_persistent.c -o /tmp/test-gmem-persistent && /tmp/test-gmem-persistent
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../runtime/nvn/vulkan/gmem_atlas_persistent.h"
int main(void) {
    uint8_t guest[4096], shadow[4096]={0};
    for (unsigned i=0;i<sizeof guest;++i) guest[i]=(uint8_t)(i*19u+7u);
    uint32_t plan[12]={128,256,0,0,1024,128,64,0,0};
    uint32_t saved[12]={128,256,512/4,0,1024,128,1024/4,0,0};
    memcpy(shadow+512,guest+128,256);
    memcpy(shadow+1024,guest+1024,128);
    assert(gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    guest[130]^=1;
    assert(!gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    guest[130]^=1;
    assert(gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    guest[1030]^=1;
    assert(!gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    guest[1030]^=1;
    saved[6]=4096/4;
    assert(!gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    saved[6]=1024/4;
    saved[4]=1028;
    assert(!gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    saved[4]=1024;
    plan[4]=4000;
    assert(!gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    plan[4]=1024;
    assert(gmem_atlas_saved_plan_matches(plan,saved,2,shadow,sizeof shadow,guest,sizeof guest));
    assert(gmem_atlas_slot_reclaimable(0, 0));
    assert(gmem_atlas_slot_reclaimable(100, 100));
    assert(gmem_atlas_slot_reclaimable(100, 105));
    assert(!gmem_atlas_slot_reclaimable(101, 100));
    // Writer 10 may be finished, but a reader in submission 18 still pins.
    assert(!gmem_atlas_slot_reclaimable(18, 10));
    assert(gmem_atlas_slot_reclaimable(18, 18));
    puts("PASS: cross-submission GMEM data and timeline lifetime");
    return 0;
}
