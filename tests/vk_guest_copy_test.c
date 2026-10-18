#include "../runtime/nvn/vulkan/guest_copy_policy.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    LasGuestCopyKey e[LAS_GCOPY_WAYS] = {0};
    assert(las_gcopy_victim(e, LAS_GCOPY_WAYS, 11, 0) == 0);
    e[0] = (LasGuestCopyKey){.addr = 0x1000, .size = 1024, .seq = 11};
    assert(las_gcopy_find(e, LAS_GCOPY_WAYS, 11, 0x1000, 256) == 0);
    assert(las_gcopy_find(e, LAS_GCOPY_WAYS, 11, 0x1000, 1024) == 0);
    assert(las_gcopy_find(e, LAS_GCOPY_WAYS, 11, 0x1000, 1025) == -1);
    assert(las_gcopy_find(e, LAS_GCOPY_WAYS, 12, 0x1000, 256) == -1);
    assert(las_gcopy_victim(e, LAS_GCOPY_WAYS, 11, 0) == 1);
    e[1] = (LasGuestCopyKey){.addr = 0x2000, .size = 512, .seq = 11};
    e[2] = (LasGuestCopyKey){.addr = 0x3000, .size = 512, .seq = 11};
    e[3] = (LasGuestCopyKey){.addr = 0x4000, .size = 512, .seq = 11};
    assert(las_gcopy_find(e, LAS_GCOPY_WAYS, 11, 0x1000, 1024) == 0);
    assert(las_gcopy_find(e, LAS_GCOPY_WAYS, 11, 0x4000, 500) == 3);
    assert(las_gcopy_victim(e, LAS_GCOPY_WAYS, 11, 5) == 1);
    assert(las_gcopy_victim(e, LAS_GCOPY_WAYS, 12, 5) == 0);
    assert(las_gcopy_bucket(0x1234, 1024) < 1024);
    assert(las_gcopy_bucket(0x1234, 1024) == las_gcopy_bucket(0x1234, 1024));
    puts("guest copy 4-way policy: PASS");
    return 0;
}
