// Test the native ARM64 -> Cpu register bridge without booting a Switch game.
// Synthetic guest values only; no kernel SVC dispatch or NSO instructions.
// This is a bridge ABI proof, not a full native thread-context implementation.
#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "cpu.h"

#if !defined(__aarch64__)
int main(void) { fputs("UNSUPPORTED: ARM64 required\n", stderr); return 2; }
#else

// Matches stack offsets in the assembly below. The register frame belongs to
// our bridge, not to the normal C calling convention or an emulated thread.
typedef struct {
    uint64_t saved_fp, saved_lr; // +0, +8
    uint64_t x[8];               // +16..+72
    uint64_t svc_id;             // +80
    uint64_t nzcv;               // +88
} BridgeFrame;
_Static_assert(sizeof(BridgeFrame) == 96, "bridge frame size");
_Static_assert(offsetof(BridgeFrame, x) == 16, "bridge x offset");
_Static_assert(offsetof(BridgeFrame, svc_id) == 80, "bridge svc offset");
_Static_assert(offsetof(BridgeFrame, nzcv) == 88, "bridge nzcv offset");

static volatile int callback_count;
__attribute__((noinline))
void mario_probe_bridge_callback(BridgeFrame *frame) {
    Cpu c = {0};
    for (unsigned i = 0; i < 8; ++i) c.x[i] = frame->x[i];
    c.nzcv = frame->nzcv;
    if (frame->svc_id != 0x45 || c.x[0] != 10 || c.x[1] != 32 ||
        c.x[2] != 3 || c.x[7] != 8) {
        fprintf(stderr, "FAIL: bridge register snapshot mismatch\n");
        callback_count = -100;
        return;
    }
    // TEST-ONLY callback: demonstrate writing a result back to guest x0.
    // No Horizon service is implemented or simulated by this calculation.
    c.x[0] += c.x[1];
    frame->x[0] = c.x[0];
    ++callback_count;
}

// AArch64 ABI: preserve x29/x30 and an aligned SP; x18 never touched.
// The frame takes 96 bytes. Calls into C with a valid x0 pointer.
// x0..x7 and NZCV are captured. Only x0 is returned from C to the caller.
// This alone does NOT preserve a complete live guest CPU/SIMD state.
__asm__(
    ".text\n"
    ".balign 4\n"
    ".global mario_probe_guest_entry\n"
    ".type mario_probe_guest_entry, %function\n"
    "mario_probe_guest_entry:\n"
    "stp x29, x30, [sp, #-96]!\n"
    "mov x29, sp\n"
    "stp x0, x1, [sp, #16]\n"
    "stp x2, x3, [sp, #32]\n"
    "stp x4, x5, [sp, #48]\n"
    "stp x6, x7, [sp, #64]\n"
    "mov x9, #0x45\n"
    "str x9, [sp, #80]\n"
    "mrs x9, nzcv\n"
    "str x9, [sp, #88]\n"
    "mov x0, sp\n"
    "bl mario_probe_bridge_callback\n"
    "ldr x0, [sp, #16]\n"
    "ldr x9, [sp, #88]\n"
    "msr nzcv, x9\n"
    "ldp x29, x30, [sp], #96\n"
    "ret\n"
    ".size mario_probe_guest_entry, .-mario_probe_guest_entry\n"
);
extern uint64_t mario_probe_guest_entry(
    uint64_t, uint64_t, uint64_t, uint64_t,
    uint64_t, uint64_t, uint64_t, uint64_t);

int main(void) {
    uint64_t result = mario_probe_guest_entry(10, 32, 3, 4, 5, 6, 7, 8);
    if (result != 42 || callback_count != 1) {
        fprintf(stderr, "FAIL: result=%" PRIu64 " callbacks=%d\n", result, callback_count);
        return 1;
    }
    puts("PASS: ARM64 x0-x7 -> real Cpu structure -> C callback -> ARM64 x0 (42).");
    puts("PASS: bridge maintains 16-byte SP alignment and saves/restores NZCV, x29/x30.");
    puts("LIMITS: callback synthetic; full x0-x30, SIMD, x18, TLS, SVC thread lifecycle unimplemented.");
    puts("NO GAME CHANGE: no NSO loaded, no Horizon SVC called, no APK rebuilt.");
    return 0;
}
#endif
