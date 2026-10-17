// Native Vulkan Scheduler V1: scoped memory barriers.
#pragma once
#include "vk.h"
#include "scheduler_policy.h"
#include <stddef.h>
void vk_sched_barrier(VkCommandBuffer cb,VkSchedDependency dep);
void vk_sched_stats_append(char *out,size_t capacity);
