// clang -std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_vk_rt_scope.c -o /tmp/las-rt-scope && /tmp/las-rt-scope
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/rt_copy_policy.h"
int main(void) {
 assert(las_rt_copy_scope_allowed(true, 10,20,1,1));
 assert(!las_rt_copy_scope_allowed(false,10,20,1,1));
 assert(!las_rt_copy_scope_allowed(true,0,20,1,1));
 assert(!las_rt_copy_scope_allowed(true,10,0,1,1));
 assert(!las_rt_copy_scope_allowed(true,10,20,0,1));
 assert(!las_rt_copy_scope_allowed(true,10,20,1,0));
 assert(las_rt_copy_image_count(10,10)==1);
 assert(las_rt_copy_image_count(10,20)==2);
 assert(las_rt_copy_aspects(10,20,1,2,0)==1);
 assert(las_rt_copy_aspects(10,20,1,2,1)==2);
 assert(las_rt_copy_aspects(10,10,1,2,0)==3);
 puts("TEST_VK_RT_SCOPE_PASS");
}
