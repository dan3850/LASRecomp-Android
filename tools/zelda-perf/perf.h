/* SPDX-License-Identifier: MIT
 * Bounded, opt-in telemetry. No Vulkan dependency: VI and JIT can use it too.
 */
#ifndef SNX_ZELDA_PERF_H
#define SNX_ZELDA_PERF_H
#include "common/cpu/aarch64/cpu.h"
enum {
    SNX_PM_TIMELINE, SNX_PM_RECYCLE, SNX_PM_RECORD_SYNC, SNX_PM_SUBMIT,
    SNX_PM_PRESENT, SNX_PM_ACQUIRE, SNX_PM_PACE, SNX_PM_JIT_WAIT,
    SNX_PM_JIT_COMPILE, SNX_PM_JIT_FAILED, SNX_PM_NO_IMAGE,
    SNX_PM_RENDER_CPU, SNX_PM_WAIT_ELIDED, SNX_PM_TEX_HASH, SNX_PM_HASH_BYTES,
    SNX_PM_TEX_UPLOAD, SNX_PM_COUNT
};
enum { SNX_PF_GUEST, SNX_PF_RENDER, SNX_PF_PRESENT, SNX_PF_COUNT };
extern int snx_perf_on; /* set before renderer/guest/recording threads start */
void snx_perf_init(void);
void snx_perf_add(int metric, u64 ns, u64 count);
/* Only SNX_PF_RENDER flushes a window, on the renderer thread. */
u64 snx_perf_frame(int stream);
#endif
