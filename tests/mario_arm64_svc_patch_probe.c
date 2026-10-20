// Stage 3: statically rewrite a synthetic ARM64 SVC into an Android host call.
// No SVC is executed. No Nintendo data, Dynarec or APK modifications.
#define _POSIX_C_SOURCE 200809L
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#if !defined(__aarch64__)
int main(void) { puts("UNSUPPORTED: ARM64 only"); return 2; }
#else
typedef uint64_t (*Fn)(void);
static volatile unsigned host_calls;
__attribute__((noinline)) static uint64_t android_hle_service(void) {
    ++host_calls;
    return 41;
}
static void write32(unsigned char *p, uint32_t w) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(w >> (8 * i));
}
int main(void) {
    long page = sysconf(_SC_PAGESIZE);
    if (page < 64) { puts("FAIL: invalid page size"); return 2; }
    unsigned char *p = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) { perror("mmap"); return 2; }
    // Original synthetic guest routine: SVC #0 ; RET.
    write32(p + 0, 0xd4000001u);
    write32(p + 4, 0xd65f03c0u);
    // Offline rewrite: replace SVC with B to a local trampoline (+16).
    // AArch64 B displacement +16 bytes: imm26=4.
    uint32_t original = 0;
    memcpy(&original, p, sizeof original);
    if (original != 0xd4000001u) {
        puts("FAIL: unexpected original instruction");
        munmap(p, (size_t)page);
        return 1;
    }
    write32(p + 0, 0x14000004u);
    // Trampoline preserves LR and frame pointer and returns to guest +4.
    // +16: STP X29, X30, [SP, #-16]!
    // +20: LDR X16, #28 -> pointer at +48
    // +24: BLR X16 (Android host service)
    // +28: ADD X0, X0, #1
    // +32: LDP X29, X30, [SP], #16
    // +36: B -32 -> guest +4
    write32(p + 16, 0xa9bf7bfdu);
    write32(p + 20, 0x580000f0u);
    write32(p + 24, 0xd63f0200u);
    write32(p + 28, 0x91000400u);
    write32(p + 32, 0xa8c17bfdu);
    write32(p + 36, 0x17fffff8u);
    Fn service = android_hle_service;
    memcpy(p + 48, &service, sizeof service);
    __builtin___clear_cache((char *)p, (char *)p + 56);
    if (mprotect(p, (size_t)page, PROT_READ | PROT_EXEC)) {
        perror("mprotect RX");
        munmap(p, (size_t)page);
        return 2;
    }
    Fn guest = (Fn)(void *)p;
    uint64_t value = guest();
    if (value != 42 || host_calls != 1) {
        fprintf(stderr, "FAIL: result=%" PRIu64 " service_calls=%u\n",
                value, host_calls);
        munmap(p, (size_t)page);
        return 1;
    }
    puts("PASS: static SVC patch -> ARM64 trampoline -> Android host -> original guest return (42).");
    puts("SCOPE: synthetic SVC only; real NSO SVC semantics, TLS, x18, relocations and game code remain untested.");
    munmap(p, (size_t)page);
    return 0;
}
#endif
