// Android-only, time-bounded attempt to help a game retry its OWN 60 Hz
// mode after a long 30 Hz episode. Never touches game code, simulated steps,
// VI events or presented frame counts. Nothing is overridden outside a probe.
// Numeric counters must come from completed real Vulkan GPU measurements.
#pragma once
#include <stdbool.h>
#include <stdint.h>
enum { LAS_RECOVERY_OFF=0, LAS_RECOVERY_PROBE=1, LAS_RECOVERY_COOLDOWN=2 };
typedef struct {
    uint16_t slow, fast, trial;
    uint16_t cooldown;
    uint8_t state;
} LasRecovery;
static inline void las_recovery_reset(LasRecovery *r) {
    *r=(LasRecovery){0};
}
// Called exactly once for each ACTUALLY presented frame.
// period_ns is the real presentation cadence; gpu_us is a smoothed real
// GPU-work estimate. Probe can begin only after 3+ seconds at half rate.
// Returns +1 when entering probe, -1 when ending it, 0 otherwise.
static inline int las_recovery_frame(LasRecovery *r,
                                     uint64_t period_ns, uint32_t gpu_us) {
    bool has_headroom=gpu_us>=1000 && gpu_us<=12000;
    bool at_30=period_ns>=28000000ull && period_ns<=42000000ull;
    bool at_60=period_ns>=10000000ull && period_ns<=21000000ull;
    // Never try to change a workload that doesn't fit in the real GPU budget.
    if (r->state==LAS_RECOVERY_PROBE) {
        if (!has_headroom || period_ns>=85000000ull) {
            r->state=LAS_RECOVERY_COOLDOWN; r->cooldown=600;
            r->slow=r->fast=r->trial=0;
            return -1;
        }
        if (r->trial < 60000) ++r->trial;
        r->fast=at_60 ? (r->fast<60000 ? r->fast+1 : r->fast) : 0;
        if (r->fast>=45 || r->trial>=180) {
            r->state=LAS_RECOVERY_COOLDOWN; r->cooldown=600;
            r->slow=r->fast=r->trial=0;
            return -1;
        }
        return 0;
    }
    if(r->state==LAS_RECOVERY_COOLDOWN) {
        if(r->cooldown) --r->cooldown;
        if(!r->cooldown) r->state=LAS_RECOVERY_OFF;
        return 0;
    }
    r->slow=at_30 && has_headroom ?
        (r->slow<60000 ? r->slow+1 : r->slow) : 0;
    if(r->slow>=90) {
        r->state=LAS_RECOVERY_PROBE; r->slow=0; r->fast=0; r->trial=0;
        return 1;
    }
    return 0;
}
static inline bool las_recovery_pulse(const LasRecovery *r) {
    return r->state==LAS_RECOVERY_PROBE;
}
