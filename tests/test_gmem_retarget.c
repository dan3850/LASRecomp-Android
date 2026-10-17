// Standalone: clang -std=c11 -O2 -Wall -Wextra -Werror
// tests/test_gmem_retarget.c -o /tmp/gmem-retarget && /tmp/gmem-retarget
#include <assert.h>
#include <string.h>
#include "../runtime/nvn/vulkan/gmem_retarget.h"

int main(void) {
    const uint64_t base = 0x7000000000ull;
    GmemRange wide[] = {{base+0x100, 64}, {base+0x200, 128}};
    GmemRange small[] = {{base+0x110, 16}, {base+0x228, 24}};
    GmemPlan resident, need;
    uint32_t tab[(GMAP_MAX+1)*4] = {0};
    assert(gmem_plan(&resident,wide,2,base,0x10000,0x10000));
    assert(gmem_plan(&need,small,2,base,0x10000,0x10000));
    assert(resident.size==192 && need.size==40);
    assert(gmem_retarget_covered(&resident,&need,tab));
    assert(tab[GMAP_MAX*4]==2);
    assert(tab[0]==0x110 && tab[1]==16 && tab[2]==4);
    assert(tab[4]==0x228 && tab[5]==24 && tab[6]==26); // (64+0x28)/4
    uint8_t guest[0x300]={0}, packed[192]={0};
    for(unsigned i=0;i<sizeof guest;i++)guest[i]=(uint8_t)((i*73+11)%251);
    memcpy(packed,guest+0x100,64);memcpy(packed+64,guest+0x200,128);
    for(unsigned i=0;i<tab[GMAP_MAX*4];++i)
       assert(!memcmp(guest+tab[4*i],packed+4*tab[4*i+2],tab[4*i+1]));

    GmemRange uncovered[]={{base+0x140,65}};
    GmemPlan wrong;
    assert(gmem_plan(&wrong,uncovered,1,base,0x10000,0x10000));
    memset(tab,0xAA,sizeof tab);
    assert(!gmem_retarget_covered(&resident,&wrong,tab));
    assert(tab[0]==0xAAAAAAAAu); // failure never changes caller table

    GmemRange exact[]={{base+0x100,64},{base+0x200,128}};
    assert(gmem_plan(&wrong,exact,2,base,0x10000,0x10000));
    assert(gmem_retarget_covered(&resident,&wrong,tab));
    assert(tab[2]==0 && tab[6]==16);
    // Inverted source/target: smaller GPU map cannot cover larger one.
    assert(!gmem_retarget_covered(&need,&resident,tab));
    return 0;
}
