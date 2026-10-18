// Android Vulkan presentation timing accumulator. No Vulkan SDK needed.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define LAS_PRESENT_SLOW_NS UINT64_C(16666667)
#define LAS_PRESENT_REPORT_NS UINT64_C(2000000000)

typedef struct {
    uint64_t since_ns, frames;
    uint64_t slot_total_ns, slot_peak_ns, slot_over_16ms;
    uint64_t acquire_total_ns, acquire_peak_ns, acquire_over_16ms;
} LasPresentWaitStats;

static inline void las_present_wait_record(LasPresentWaitStats *s, uint64_t now_ns,
                                            uint64_t slot_ns, uint64_t acquire_ns) {
    if (!s->frames) s->since_ns = now_ns;
    ++s->frames;
    s->slot_total_ns += slot_ns;
    s->acquire_total_ns += acquire_ns;
    if (slot_ns > s->slot_peak_ns) s->slot_peak_ns = slot_ns;
    if (acquire_ns > s->acquire_peak_ns) s->acquire_peak_ns = acquire_ns;
    if (slot_ns >= LAS_PRESENT_SLOW_NS) ++s->slot_over_16ms;
    if (acquire_ns >= LAS_PRESENT_SLOW_NS) ++s->acquire_over_16ms;
}

static inline bool las_present_wait_due(const LasPresentWaitStats *s, uint64_t now_ns) {
    return s->frames && now_ns >= s->since_ns &&
           now_ns - s->since_ns >= LAS_PRESENT_REPORT_NS;
}
