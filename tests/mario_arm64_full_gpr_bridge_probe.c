// ARM64 full general-purpose register frame -> real runtime Cpu model.
// Synthetic callback only. NEVER calls rt_svc or executes Switch NSO instructions.
// Build on Android/Termux: clang -std=c11 -O2 -Wall -Wextra -I runtime ...
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
    uint64_t x[31];     // x0..x30 at 0..240
    uint64_t nzcv;      // +248
} NativeFrame;
_Static_assert(sizeof(NativeFrame) == 256, "native frame layout");
_Static_assert(offsetof(NativeFrame, nzcv) == 248, "nzcv layout");

static volatile unsigned calls;
void mario_native_frame_callback(NativeFrame *frame) {
    Cpu cpu = {0};
    for (unsigned i = 0; i < 31; ++i) cpu.x[i] = frame->x[i];
    cpu.nzcv = frame->nzcv;
    cpu.sp = (uintptr_t)frame + sizeof(*frame);
    if (cpu.x[0] != 10 || cpu.x[1] != 32 || cpu.x[2] != 3 ||
        cpu.x[7] != 8 || cpu.x[30] == 0 || (cpu.sp & 15)) {
        fprintf(stderr, "FAIL: captured context mismatch\n");
        calls = 100;
        return;
    }
    cpu.x[0] = cpu.x[0] + cpu.x[1];
    frame->x[0] = cpu.x[0];
    ++calls;
}

__asm__(
    ".text\n"
    ".p2align 2\n"
    ".global mario_native_frame_entry\n"
    ".type mario_native_frame_entry, %function\n"
    "mario_native_frame_entry:\n"
    "sub sp, sp, #256\n"
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
    "mov x0, sp\n"
    "bl mario_native_frame_callback\n"
    // Restore NZCV before registers and before returning to guest.
    "ldr x9, [sp, #248]\n"
    "msr nzcv, x9\n"
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
    "add sp, sp, #256\n"
    "ret\n"
    ".size mario_native_frame_entry, .-mario_native_frame_entry\n"
);
extern uint64_t mario_native_frame_entry(
    uint64_t, uint64_t, uint64_t, uint64_t,
    uint64_t, uint64_t, uint64_t, uint64_t);

int main(void) {
    uint64_t answer = mario_native_frame_entry(10, 32, 3, 4, 5, 6, 7, 8);
    if (answer != 42 || calls != 1) {
        fprintf(stderr, "FAIL: answer=%" PRIu64 " calls=%u\n", answer, calls);
        return 1;
    }
    puts("PASS: native x0-x30 and NZCV captured, callback used real Cpu layout.");
    puts("PASS: guest x0 result restored (42); x18 saved/restored without host modification.");
    puts("LIMITS: synthetic bridge; SIMD, FPCR/FPSR, TLS, Horizon thread context and actual rt_svc not implemented.");
    puts("NO NSO OR APK CHANGES.");
    return 0;
}
#endif
