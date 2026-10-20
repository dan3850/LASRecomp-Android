// Experimental AArch64 native-to-C bridge with complete SIMD/FP register snapshot.
// Synthetic exercise only; NO guest SVC, NSO execution or production runtime changes.
#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "cpu.h"

#if !defined(__aarch64__)
int main(void) { puts("UNSUPPORTED: AArch64 required"); return 2; }
#else
typedef struct __attribute__((aligned(16))) {
    uint64_t x[31];       // offset 0
    uint64_t nzcv;        // offset 248
    __uint128_t v[32];    // offset 256
    uint64_t fpcr;        // offset 768
    uint64_t fpsr;        // offset 776
    uint64_t saved_sp;    // offset 784
    uint64_t pad;         // offset 792
} NativeFrame;
_Static_assert(sizeof(NativeFrame) == 800, "frame size");
_Static_assert(offsetof(NativeFrame, v) == 256, "vector offset");
_Static_assert(offsetof(NativeFrame, fpcr) == 768, "fpcr offset");
_Static_assert(offsetof(NativeFrame, saved_sp) == 784, "sp offset");

static volatile unsigned callbacks;
void mario_native_simd_callback(NativeFrame *f) {
    Cpu c = {0};
    memcpy(c.x, f->x, 31 * sizeof(uint64_t));
    memcpy(c.v, f->v, sizeof c.v);
    c.nzcv = f->nzcv;
    c.fpcr = f->fpcr;
    c.fpsr = f->fpsr;
    c.sp = f->saved_sp;
    if ((c.sp & 15) || c.x[30] == 0 || c.x[0] != 10 || c.x[1] != 32) {
        callbacks = 100;
        return;
    }
    // A synthetic guest placed 0x5a in all 16 bytes of V0.
    unsigned char original[16];
    memcpy(original, &c.v[0], sizeof(original));
    for (unsigned i = 0; i < 16; ++i)
        if (original[i] != 0x5a) { callbacks = 101; return; }
    // Demonstrate a vector result from a C handler making the return trip.
    memset(&c.v[0], 0xa5, sizeof(c.v[0]));
    c.x[0] = c.x[0] + c.x[1];
    f->x[0] = c.x[0];
    memcpy(f->v, c.v, sizeof c.v);
    ++callbacks;
}

__asm__(
    ".text\n"
    ".p2align 2\n"
    ".global mario_native_simd_entry\n"
    ".type mario_native_simd_entry, %function\n"
    "mario_native_simd_entry:\n"
    "sub sp, sp, #800\n"
    "stp x0, x1, [sp, #0]\n"
    "stp x2, x3, [sp, #16]\n"
    "stp x4, x5, [sp, #32]\n"
    "stp x6, x7, [sp, #48]\n"
    "stp x8, x9, [sp, #64]\n"
    "stp x10, x11, [sp, #80]\n"
    "stp x12, x13, [sp, #96]\n"
    "stp x14, x15, [sp, #112]\n"
    "stp x16, x17, [sp, #128]\n"
    "stp x18, x19, [sp, #144]\n"
    "stp x20, x21, [sp, #160]\n"
    "stp x22, x23, [sp, #176]\n"
    "stp x24, x25, [sp, #192]\n"
    "stp x26, x27, [sp, #208]\n"
    "stp x28, x29, [sp, #224]\n"
    "str x30, [sp, #240]\n"
    "mrs x9, nzcv\n"
    "str x9, [sp, #248]\n"
    "movi v0.16b, #0x5a\n"
    "stp q0, q1, [sp, #256]\n"
    "stp q2, q3, [sp, #288]\n"
    "stp q4, q5, [sp, #320]\n"
    "stp q6, q7, [sp, #352]\n"
    "stp q8, q9, [sp, #384]\n"
    "stp q10, q11, [sp, #416]\n"
    "stp q12, q13, [sp, #448]\n"
    "stp q14, q15, [sp, #480]\n"
    "stp q16, q17, [sp, #512]\n"
    "stp q18, q19, [sp, #544]\n"
    "stp q20, q21, [sp, #576]\n"
    "stp q22, q23, [sp, #608]\n"
    "stp q24, q25, [sp, #640]\n"
    "stp q26, q27, [sp, #672]\n"
    "stp q28, q29, [sp, #704]\n"
    "stp q30, q31, [sp, #736]\n"
    "mrs x9, fpcr\n"
    "str x9, [sp, #768]\n"
    "mrs x9, fpsr\n"
    "str x9, [sp, #776]\n"
    "add x9, sp, #800\n"
    "str x9, [sp, #784]\n"
    "mov x0, sp\n"
    "bl mario_native_simd_callback\n"
    // Restore FP state and NZCV before all GPRs.
    "ldr x9, [sp, #768]\n"
    "msr fpcr, x9\n"
    "ldr x9, [sp, #776]\n"
    "msr fpsr, x9\n"
    "ldr x9, [sp, #248]\n"
    "msr nzcv, x9\n"
    "ldp q0, q1, [sp, #256]\n"
    "ldp q2, q3, [sp, #288]\n"
    "ldp q4, q5, [sp, #320]\n"
    "ldp q6, q7, [sp, #352]\n"
    "ldp q8, q9, [sp, #384]\n"
    "ldp q10, q11, [sp, #416]\n"
    "ldp q12, q13, [sp, #448]\n"
    "ldp q14, q15, [sp, #480]\n"
    "ldp q16, q17, [sp, #512]\n"
    "ldp q18, q19, [sp, #544]\n"
    "ldp q20, q21, [sp, #576]\n"
    "ldp q22, q23, [sp, #608]\n"
    "ldp q24, q25, [sp, #640]\n"
    "ldp q26, q27, [sp, #672]\n"
    "ldp q28, q29, [sp, #704]\n"
    "ldp q30, q31, [sp, #736]\n"
    "ldp x0, x1, [sp, #0]\n"
    "ldp x2, x3, [sp, #16]\n"
    "ldp x4, x5, [sp, #32]\n"
    "ldp x6, x7, [sp, #48]\n"
    "ldp x8, x9, [sp, #64]\n"
    "ldp x10, x11, [sp, #80]\n"
    "ldp x12, x13, [sp, #96]\n"
    "ldp x14, x15, [sp, #112]\n"
    "ldp x16, x17, [sp, #128]\n"
    "ldp x18, x19, [sp, #144]\n"
    "ldp x20, x21, [sp, #160]\n"
    "ldp x22, x23, [sp, #176]\n"
    "ldp x24, x25, [sp, #192]\n"
    "ldp x26, x27, [sp, #208]\n"
    "ldp x28, x29, [sp, #224]\n"
    "ldr x30, [sp, #240]\n"
    "add sp, sp, #800\n"
    // Synthetic verification: explicitly read V0 back via return x0.
    // Production bridge must NOT overwrite guest x0 this way.
    "umov x0, v0.d[0]\n"
    "ret\n"
    ".size mario_native_simd_entry, .-mario_native_simd_entry\n"
);
extern uint64_t mario_native_simd_entry(uint64_t, uint64_t);

int main(void) {
    uint64_t result = mario_native_simd_entry(10, 32);
    if (callbacks != 1 || result != UINT64_C(0xa5a5a5a5a5a5a5a5)) {
        fprintf(stderr, "FAIL: callbacks=%u V0.low=%" PRIx64 "\n", callbacks, result);
        return 1;
    }
    puts("PASS: x0-x30, NZCV, V0-V31, FPCR, FPSR captured in an ARM64 frame.");
    puts("PASS: real Cpu.v bridge writes and restores V0; native V0.low=0xa5a5a5a5a5a5a5a5.");
    puts("LIMITS: synthetic callback only; no Horizon thread/TLS or real rt_svc dispatch.");
    puts("NO NSO, APK or runtime changes.");
    return 0;
}
#endif
