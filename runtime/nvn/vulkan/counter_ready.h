// Non-blocking GPU query completion policy.
// Guest reports are first written provisionally; as soon as a submission's
// timeline value completes, read and deliver its actual GPU timestamps.
// The helper never waits on a fence, changes time values or fabricates frames.
#pragma once
#include <stdbool.h>
#include <stdint.h>
static inline bool vk_counter_completion_advanced(
    uint64_t completed, uint64_t *last_polled) {
    if (!last_polled || completed <= *last_polled) return false;
    *last_polled = completed;
    return true;
}
static inline bool vk_counter_host_overstates_gpu(
    uint64_t prev_host_ticks, uint64_t host_ticks,
    double gpu_ms, double switch_tick_ns) {
    if (host_ticks < prev_host_ticks || switch_tick_ns <= 0) return false;
    double host_ms = (host_ticks - prev_host_ticks) * switch_tick_ns / 1e6;
    return host_ms >= 16.67 && gpu_ms < 13.0;
}
