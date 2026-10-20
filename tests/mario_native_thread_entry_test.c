// Validate the actual runtime/mario_native_thread_entry.S host-x18 boundary.
// Synthetic leaf only: never execute Switch NSO / Horizon SVC.
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

#if defined(__aarch64__)
extern uint64_t mario_native_call_leaf(uint64_t (*guest)(void *),
                                       void *arg, uint64_t guest_x18);
extern uint64_t mario_native_x18_guest(void *);
__asm__(
".text\n"
".p2align 2\n"
".global mario_native_x18_guest\n"
".type mario_native_x18_guest, %function\n"
"mario_native_x18_guest:\n"
"cmp x18, x0\n"
"b.ne 1f\n"
"mov x18, #0x1234\n"
"mov x0, #42\n"
"ret\n"
"1:\n"
"mov x0, #0\n"
"ret\n"
".size mario_native_x18_guest, .-mario_native_x18_guest\n"
);
static uint64_t read_x18(void) {
    uint64_t value;
    __asm__ volatile("mov %0, x18" : "=r"(value));
    return value;
}
int main(void) {
    uint64_t host_before = read_x18();
    const uint64_t guest_value = UINT64_C(0x2750);
    for (unsigned i = 0; i < 64; ++i) {
        uint64_t result = mario_native_call_leaf(mario_native_x18_guest,
                                                (void *)(uintptr_t)guest_value,
                                                guest_value);
        uint64_t host_after = read_x18();
        if (result != 42 || host_before != host_after) {
            fprintf(stderr,
                    "FAIL: iteration=%u result=%" PRIu64
                    " host_before=%" PRIx64 " host_after=%" PRIx64 "\n",
                    i, result, host_before, host_after);
            return 1;
        }
    }
    puts("PASS: real runtime ARM64 entry used guest x18 and restored Android x18 (64 calls).");
    puts("LIMIT: synthetic ABI-safe leaf. No guest TLS writes, real SVC, or Mario boot.");
    return 0;
}
#else
int main(void) { puts("UNSUPPORTED: ARM64 only"); return 2; }
#endif
