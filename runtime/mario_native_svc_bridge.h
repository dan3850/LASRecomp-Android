// ARM64 native SVC context shared with an eventual trampoline.
// Not part of the current static-recompiler ABI.
#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct __attribute__((aligned(16))) MarioNativeSvcFrame {
    uint64_t x[31];       // x0..x30
    uint64_t nzcv;
    __uint128_t v[32];    // q0..q31
    uint64_t fpcr, fpsr;
    uint64_t guest_sp;    // original guest stack, NOT host C stack
    uint64_t reserved;
} MarioNativeSvcFrame;

_Static_assert(offsetof(MarioNativeSvcFrame, x) == 0, "x offset");
_Static_assert(offsetof(MarioNativeSvcFrame, nzcv) == 248, "nzcv offset");
_Static_assert(offsetof(MarioNativeSvcFrame, v) == 256, "SIMD offset");
_Static_assert(offsetof(MarioNativeSvcFrame, fpcr) == 768, "fpcr offset");
_Static_assert(offsetof(MarioNativeSvcFrame, fpsr) == 776, "fpsr offset");
_Static_assert(offsetof(MarioNativeSvcFrame, guest_sp) == 784, "sp offset");
_Static_assert(sizeof(MarioNativeSvcFrame) == 800, "frame size");

enum {
    MARIO_NATIVE_SVC_OK = 0,
    MARIO_NATIVE_SVC_NO_THREAD = -1,
    MARIO_NATIVE_SVC_BAD_FRAME = -2,
    MARIO_NATIVE_SVC_BAD_PC = -3
};

// Only enabled with LASRECOMP_MARIO_NATIVE_SVC_BRIDGE, and only callable from
// a real kernel-managed guest thread. Calls may nonlocally exit via kernel.c.
#if defined(LASRECOMP_MARIO_TEST) && defined(__aarch64__) && defined(LASRECOMP_MARIO_NATIVE_SVC_BRIDGE)
int mario_native_svc_from_frame(MarioNativeSvcFrame *frame, uint32_t svc_id, uint64_t guest_pc);
#endif
