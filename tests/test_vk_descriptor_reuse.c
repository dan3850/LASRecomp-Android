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
 // Unused entries MUST NOT enter the hash/equality check, and partial
 // copying must retain the complete prefix but leave destination tail alone.
 LasDsKey compact={0},noisy={0},dest={0};
 compact.layout=0x999; compact.count=1; compact.reserved=0;
 compact.binds[0]=(LasDsBind){8,6,0xabc,32,128};
 noisy=compact;
 for (unsigned i=1;i<LAS_DS_LIMIT;++i)
   noisy.binds[i]=(LasDsBind){i,7,i+1,i+2,i+3};
 assert(las_ds_hash(&compact)==las_ds_hash(&noisy));
 assert(las_ds_equal(&compact,&noisy));
 memset(&dest,0xA5,sizeof dest);
 assert(las_ds_copy(&dest,&compact));
 assert(las_ds_equal(&dest,&compact));
 assert(dest.binds[1].a==UINT64_C(0xA5A5A5A5A5A5A5A5));
 assert(las_ds_size(&compact)==offsetof(LasDsKey,binds)+sizeof(LasDsBind));
 assert(!las_ds_copy(NULL,&compact));
 assert(!las_ds_copy(&dest,NULL));
 puts("TEST_VK_DESCRIPTOR_REUSE_PASS");
}
