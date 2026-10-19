// Monotonic host-side 60 Hz cap for the optional Stable60 game mod.
// Never changes guest simulation, counters or VI clock.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define LAS_MOD60_PERIOD_NS UINT64_C(16666667)

typedef struct {
    uint64_t last_present_ns;
} LasMod60Pacer;

// Called at the start of each presentation. Zero means no sleep is needed.
// A late frame does not accrue debt: never run a burst of catch-up frames.
static inline uint64_t las_mod60_deadline(LasMod60Pacer *p,
                                           bool enabled, uint64_t now) {
    if (!enabled) {
        p->last_present_ns = 0;
        return 0;
    }
    if (!p->last_present_ns || now <= p->last_present_ns) {
        p->last_present_ns = now;
        return 0;
    }
    uint64_t elapsed = now - p->last_present_ns;
    if (elapsed >= LAS_MOD60_PERIOD_NS) {
        p->last_present_ns = now;
        return 0;
    }
    return p->last_present_ns + LAS_MOD60_PERIOD_NS;
}

// Commit the ACTUAL wakeup time (not the theoretical deadline).
// This prevents accumulated drift and avoids accelerating after stalls.
static inline void las_mod60_complete(LasMod60Pacer *p, uint64_t now) {
    p->last_present_ns = now;
}
