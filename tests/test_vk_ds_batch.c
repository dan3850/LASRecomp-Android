// clang -std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_vk_ds_batch.c -o /tmp/test_vk_ds_batch && /tmp/test_vk_ds_batch
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/descriptor_batch_policy.h"
int main(void) {
 assert((LAS_DS_BATCH_SLOTS & (LAS_DS_BATCH_SLOTS-1))==0);
 for (unsigned i=0;i<10000;i++)
     assert(las_ds_batch_slot(0x1000u+i) < LAS_DS_BATCH_SLOTS);
 assert(las_ds_batch_take_allowed(100,100,0x1234,0x1234,1,4));
 assert(!las_ds_batch_take_allowed(100,101,0x1234,0x1234,1,4));
 assert(!las_ds_batch_take_allowed(100,100,0x1234,0x1238,1,4));
 assert(!las_ds_batch_take_allowed(100,100,0x1234,0x1234,4,4));
 assert(!las_ds_batch_take_allowed(100,100,0x1234,0x1234,0,5));
 unsigned seen=1;
 for (unsigned i=1;i<LAS_DS_BATCH_WIDTH;i++) {
     assert(las_ds_batch_take_allowed(9,9,12,12,i,LAS_DS_BATCH_WIDTH));
     seen++;
 }
 assert(seen==LAS_DS_BATCH_WIDTH);
 assert(las_ds_batch_remaining(1,4)==3);
 assert(las_ds_batch_remaining(4,4)==0);
 assert(las_ds_batch_remaining(5,4)==0);
 assert(las_ds_batch_remaining(0,6)==0);
 puts("TEST_VK_DS_BATCH_PASS");
}
