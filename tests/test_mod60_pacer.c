// Host test:
// clang -std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined \
//   tests/test_mod60_pacer.c -o /tmp/test_mod60_pacer && /tmp/test_mod60_pacer
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/mod60_pacer.h"
int main(void) {
    LasMod60Pacer p={0};
    uint64_t n=UINT64_C(1000000000);
    assert(las_mod60_deadline(&p,false,n)==0);
    assert(p.last_present_ns==0);
    assert(las_mod60_deadline(&p,true,n)==0);
    assert(las_mod60_deadline(&p,true,n+UINT64_C(10000000))==n+LAS_MOD60_PERIOD_NS);
    las_mod60_complete(&p,n+LAS_MOD60_PERIOD_NS+UINT64_C(50000));
    n=p.last_present_ns;
    assert(las_mod60_deadline(&p,true,n+1)==n+LAS_MOD60_PERIOD_NS);
    // 35-ms draw misses vsync: never attempt extra fast catch-up frames.
    assert(las_mod60_deadline(&p,true,n+UINT64_C(35000000))==0);
    assert(p.last_present_ns==n+UINT64_C(35000000));
    assert(las_mod60_deadline(&p,true,p.last_present_ns+UINT64_C(1000000))==
           p.last_present_ns+LAS_MOD60_PERIOD_NS);
    // Turning the mod off resets the cap immediately.
    assert(las_mod60_deadline(&p,false,p.last_present_ns+1)==0);
    assert(p.last_present_ns==0);
    assert(las_mod60_deadline(&p,true,UINT64_C(5000000000))==0);
    puts("TEST_MOD60_PACER_PASS");
}
