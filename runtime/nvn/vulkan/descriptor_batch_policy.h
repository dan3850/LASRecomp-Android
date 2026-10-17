// No Vulkan dependency: single-submission batching policy used by
// vkAllocateDescriptorSets. Every returned descriptor handle must be consumed
// exactly once and never survive pool reset or a new submission.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#define LAS_DS_BATCH_WIDTH 4u
#define LAS_DS_BATCH_SLOTS 128u
static inline unsigned las_ds_batch_slot(uint64_t layout) {
 // Vulkan non-dispatchable handles have at least 4-byte alignment on target.
 layout ^= layout >> 29;
 layout ^= layout >> 13;
 return (unsigned)(layout & (LAS_DS_BATCH_SLOTS-1));
}
static inline bool las_ds_batch_take_allowed(
 uint64_t saved_seq, uint64_t next_seq,
 uint64_t saved_layout, uint64_t needed_layout,
 uint32_t next, uint32_t count) {
 return saved_seq == next_seq && saved_layout == needed_layout
     && next < count && count <= LAS_DS_BATCH_WIDTH;
}
static inline unsigned las_ds_batch_remaining(uint32_t next, uint32_t count) {
 return count <= LAS_DS_BATCH_WIDTH && next <= count ? count-next : 0;
}
