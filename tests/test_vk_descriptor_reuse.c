// clang -std=c11 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_vk_descriptor_reuse.c -o /tmp/las-ds && /tmp/las-ds
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/descriptor_reuse_policy.h"
int main(void) {
 LasDsKey a={0},b={0};
 a.layout=0x12345; a.count=2;
 a.binds[0]=(LasDsBind){0,6,0x100,12,128};
 a.binds[1]=(LasDsBind){32,1,0x200,0x300,1};
 b=a;
 uint64_t h=las_ds_hash(&a);
 assert(h && las_ds_hash(&b)==h && las_ds_equal(&a,&b));
 assert(las_ds_valid(10,10,h,h,&a,&b));
 assert(!las_ds_valid(9,10,h,h,&a,&b));
 assert(!las_ds_valid(10,10,h,h+1,&a,&b));
 b.binds[0].b++; assert(!las_ds_equal(&a,&b));
 b=a; b.binds[1].b++; assert(!las_ds_equal(&a,&b));
 b=a; b.binds[1].c++; assert(!las_ds_equal(&a,&b));
 b=a; b.layout++; assert(!las_ds_equal(&a,&b));
 b=a; b.count=1; assert(!las_ds_equal(&a,&b));
 b=a; b.binds[1].type++; assert(!las_ds_equal(&a,&b));
 b=a; b.count=LAS_DS_LIMIT+1; assert(!las_ds_equal(&a,&b));
 assert(!las_ds_hash(&b));
 puts("TEST_VK_DESCRIPTOR_REUSE_PASS");
}
