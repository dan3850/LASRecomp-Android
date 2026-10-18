// Small, GPU-driver-friendly shader/pipeline compile worker budget.
// The Android default is tuned for A/B comparison with LASRecomp PR #91.
#pragma once
#include <stdbool.h>

static inline int las_vk_worker_count(int logical_cpus, bool android,
                                       const char *requested_env) {
    int desktop = logical_cpus - 4;
    if (desktop < 4) desktop = 4;
    if (desktop > 16) desktop = 16;
    int fallback = android ? 3 : desktop;
    if (!requested_env || !*requested_env) return fallback;

    int requested = 0;
    for (const char *p = requested_env; *p; ++p) {
        if (*p < '0' || *p > '9') return fallback;
        requested = requested * 10 + (*p - '0');
        if (requested > 16) return fallback;
    }
    return requested > 0 ? requested : fallback;
}
