// Second-stage ARM64-native feasibility test for Android/Termux.
// Synthetic AArch64 only: PC-relative literal load -> BLR into the Android host
// -> return to guest -> return to caller. No Switch files or APK changes.
#define _POSIX_C_SOURCE 200809L
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#if !defined(__aarch64__)
int main(void) {
    fputs("UNSUPPORTED: ARM64 only\n", stderr);
    return 2;
}
#else
typedef uint64_t (*guest_fn)(void);

__attribute__((noinline))
static uint64_t host_service(void) {
    return 41;
}

static void put32(unsigned char *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> (i * 8));
}

static int run_one(unsigned iteration, long page) {
    unsigned char *code = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (code == MAP_FAILED) { perror("mmap"); return 1; }
    // 0:  stp x29, x30, [sp, #-16]!
    // 4:  ldr x16, #20   ; literal at offset 24 (PC-relative, no fixed base)
    // 8:  blr x16       ; calls the host service
    // 12: add x0, x0, #1
    // 16: ldp x29, x30, [sp], #16
    // 20: ret
    // 24: host_service pointer (8-byte literal)
    put32(code + 0, 0xa9bf7bfdu);
    put32(code + 4, 0x580000b0u);
    put32(code + 8, 0xd63f0200u);
    put32(code + 12, 0x91000400u);
    put32(code + 16, 0xa8c17bfdu);
    put32(code + 20, 0xd65f03c0u);

    // Store a function pointer as an absolute relocation in synthetic code.
    // memcpy avoids relying on function-pointer aliasing.
    guest_fn cb = host_service;
    memcpy(code + 24, &cb, sizeof cb);
    __builtin___clear_cache((char *)code, (char *)code + 32);
    if (mprotect(code, (size_t)page, PROT_READ | PROT_EXEC)) {
        perror("mprotect(RX)");
        munmap(code, (size_t)page);
        return 1;
    }
    guest_fn guest = (guest_fn)(void *)code;
    uint64_t value = guest();
    if (value != 42) {
        fprintf(stderr, "FAIL iteration %u: result=%" PRIu64 "\n", iteration, value);
        munmap(code, (size_t)page);
        return 1;
    }
    if (munmap(code, (size_t)page)) { perror("munmap"); return 1; }
    return 0;
}

int main(void) {
    long page = sysconf(_SC_PAGESIZE);
    if (page < 32) { fputs("FAIL: page size\n", stderr); return 2; }
    // Repeated mappings test that the code does not depend on one fixed address.
    for (unsigned i = 0; i < 8; ++i) {
        if (run_one(i, page)) return 1;
    }
    puts("PASS: ARM64 guest -> Android host BLR -> guest -> caller (42), 8 mappings.");
    puts("SCOPE: synthetic relocation only; NSO loader, x18, TLS, SVC, actual game code NOT tested.");
    return 0;
}
#endif
