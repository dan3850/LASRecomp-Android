// Minimal AArch64 direct-execution feasibility probe for Android/Termux.
// No Nintendo files, no emulator, no game runtime and no modifications to Mario.
// Build: clang -std=c11 -O2 -Wall -Wextra tests/mario_arm64_native_probe.c -o /tmp/mario-arm64-probe
// Run:   /tmp/mario-arm64-probe
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#if !defined(__aarch64__)
int main(void) {
    fputs("UNSUPPORTED: probe must run on an ARM64 device.\n", stderr);
    return 2;
}
#else
typedef uint64_t (*guest_function)(void);

static void put32(unsigned char *dst, uint32_t instruction) {
    dst[0] = (unsigned char)instruction;
    dst[1] = (unsigned char)(instruction >> 8);
    dst[2] = (unsigned char)(instruction >> 16);
    dst[3] = (unsigned char)(instruction >> 24);
}

int main(void) {
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) {
        perror("sysconf(_SC_PAGESIZE)");
        return 2;
    }
    unsigned char *code = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (code == MAP_FAILED) {
        perror("mmap(RW)");
        return 2;
    }

    // Offset 0: movz x0, #42 ; ret.
    put32(code + 0, 0xd2800540u);
    put32(code + 4, 0xd65f03c0u);
    // Offset 16: ldr x16, [pc, #8] ; br x16 ; <64-bit absolute target>.
    // This exercises a real guest-style indirect branch, without a function table.
    put32(code + 16, 0x58000050u);
    put32(code + 20, 0xd61f0200u);
    uintptr_t destination = (uintptr_t)(code + 0);
    memcpy(code + 24, &destination, sizeof(destination));

    __builtin___clear_cache((char *)code, (char *)code + 32);
    if (mprotect(code, (size_t)page, PROT_READ | PROT_EXEC) != 0) {
        fprintf(stderr, "BLOCKED: Android refused anonymous RW->RX mapping: %s\n",
                strerror(errno));
        munmap(code, (size_t)page);
        return 2;
    }

    guest_function entry = (guest_function)(void *)(code + 16);
    uint64_t result = entry();
    if (result != 42) {
        fprintf(stderr, "FAIL: indirect ARM64 call returned %" PRIu64 " (expected 42)\n", result);
        munmap(code, (size_t)page);
        return 1;
    }
    puts("PASS: native ARM64 executable mapping, indirect BR, and return to host (42).");
    puts("SCOPE: synthetic instructions only; NSO relocations, TLS, SVC, x18 and game integration NOT tested.");
    munmap(code, (size_t)page);
    return 0;
}
#endif
