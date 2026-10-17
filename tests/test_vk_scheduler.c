// clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_vk_scheduler.c -o /tmp/test-vk-scheduler && /tmp/test-vk-scheduler
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/scheduler_policy.h"
int main(void) {
 for(int i=0;i<VKSCHED_COUNT;++i) {
  VkSchedPolicy p=vk_sched_policy((VkSchedDependency)i);
  assert(p.src_stage && p.dst_stage && p.src_access && p.dst_access);
  assert((p.dst_access&(VKSCHED_READ|VKSCHED_WRITE))==(VKSCHED_READ|VKSCHED_WRITE));
 }
 assert(vk_sched_policy(VKSCHED_BEFORE_GRAPHICS).dst_stage==VKSCHED_STAGE_GRAPHICS);
 assert(vk_sched_policy(VKSCHED_BEFORE_COMPUTE).dst_stage==VKSCHED_STAGE_COMPUTE);
 assert(vk_sched_policy(VKSCHED_BEFORE_TRANSFER).dst_stage==VKSCHED_STAGE_TRANSFER);
 assert(vk_sched_policy(VKSCHED_UPLOAD_READY).src_stage==VKSCHED_STAGE_TRANSFER);
 assert(vk_sched_policy(VKSCHED_TRANSFER_TO_COMPUTE).dst_stage==VKSCHED_STAGE_COMPUTE);
 assert(vk_sched_policy(VKSCHED_COMPUTE_TO_TRANSFER).src_stage==VKSCHED_STAGE_COMPUTE);
 assert(vk_sched_policy(VKSCHED_TRANSFER_TO_ALL).src_access==VKSCHED_TRANSFER_WRITE);
 assert(vk_sched_policy((VkSchedDependency)999).src_stage==VKSCHED_STAGE_ALL);
 puts("TEST_VK_SCHEDULER_PASS");
 return 0;
}
