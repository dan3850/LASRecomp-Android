// Native Vulkan Scheduler V1. Scoped execution dependencies in the existing
// single Vulkan queue; no speculative reordering or changes to guest fences.
#include "scheduler.h"
#include "../../rt.h"
#include <stdio.h>
#include <stdlib.h>

static int sched_on=-1;
static uint64_t calls[VKSCHED_COUNT],fallback_calls;
static int enabled(void) {
 if(sched_on<0) {
  const char *v=getenv("LARECOMP_VK_SCHEDULER");
#ifdef __ANDROID__
  sched_on=!v || atoi(v)!=0;
#else
  sched_on=v && atoi(v)!=0;
#endif
  LOG("[vk-scheduler] scoped barriers %s (LARECOMP_VK_SCHEDULER=%s)\n",sched_on?"on":"off",v?v:"unset");
 }
 return sched_on;
}
static VkPipelineStageFlags2 stage(uint32_t s) {
 switch(s) {
 case VKSCHED_STAGE_GRAPHICS: return VK_PIPELINE_STAGE_2_ALL_GRAPHICS_BIT;
 case VKSCHED_STAGE_COMPUTE: return VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT;
 case VKSCHED_STAGE_TRANSFER: return VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT;
 default: return VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
 }
}
static VkAccessFlags2 access_mask(uint32_t a) {
 if(a==VKSCHED_TRANSFER_WRITE) return VK_ACCESS_2_TRANSFER_WRITE_BIT;
 return ((a&VKSCHED_READ)?VK_ACCESS_2_MEMORY_READ_BIT:0)
      | ((a&VKSCHED_WRITE)?VK_ACCESS_2_MEMORY_WRITE_BIT:0);
}
void vk_sched_barrier(VkCommandBuffer cb,VkSchedDependency dep) {
 if(!enabled() || dep<0 || dep>=VKSCHED_COUNT) {
  fallback_calls++;
  vk_full_barrier(cb);
  return;
 }
 VkSchedPolicy p=vk_sched_policy(dep);
 VkMemoryBarrier2 mb={
  .sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
  .srcStageMask=stage(p.src_stage),.srcAccessMask=access_mask(p.src_access),
  .dstStageMask=stage(p.dst_stage),.dstAccessMask=access_mask(p.dst_access)};
 VkDependencyInfo di={
  .sType=VK_STRUCTURE_TYPE_DEPENDENCY_INFO,
  .memoryBarrierCount=1,.pMemoryBarriers=&mb};
 vkCmdPipelineBarrier2(cb,&di);
 calls[dep]++;
}
void vk_sched_stats_append(char *out,size_t cap) {
 if(!cap) return;
 snprintf(out,cap," | sched pass %llu cs %llu xfer %llu upload %llu t-c %llu c-t %llu t-all %llu fallback %llu",
  (unsigned long long)calls[VKSCHED_BEFORE_GRAPHICS],
  (unsigned long long)calls[VKSCHED_BEFORE_COMPUTE],
  (unsigned long long)calls[VKSCHED_BEFORE_TRANSFER],
  (unsigned long long)calls[VKSCHED_UPLOAD_READY],
  (unsigned long long)calls[VKSCHED_TRANSFER_TO_COMPUTE],
  (unsigned long long)calls[VKSCHED_COMPUTE_TO_TRANSFER],
  (unsigned long long)calls[VKSCHED_TRANSFER_TO_ALL],
  (unsigned long long)fallback_calls);
 for(int i=0;i<VKSCHED_COUNT;++i) calls[i]=0;
 fallback_calls=0;
}
