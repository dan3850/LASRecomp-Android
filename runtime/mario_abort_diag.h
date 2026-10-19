// Read fatal diagnostics through the OS so a bad guest pointer cannot fault
// while reporting the original failure. Used only by the Mario Android test.
#include <fcntl.h>
#include <stdint.h>
#include <unistd.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/uio.h>

static __thread uint64_t mario_abort_stack_lo, mario_abort_stack_hi;

static int mario_abort_read(int fd, uint64_t address, void *buffer, size_t size) {
    if (address < GUEST_LO || address >= GUEST_HI || size > GUEST_HI - address)
        return 0;
    if (fd >= 0 && pread(fd, buffer, size, (off_t)address) == (ssize_t)size) return 1;
#ifdef SYS_process_vm_readv
    struct iovec local = {buffer, size}, remote = {(void *)(uintptr_t)address, size};
    if (syscall(SYS_process_vm_readv, getpid(), &local, 1, &remote, 1, 0) == (ssize_t)size) return 1;
#endif
    // Caller supplies only the readable, committed region containing the active
    // guest stack. Never dereference an arbitrary guest pointer as a fallback.
    if (address >= mario_abort_stack_lo && address < mario_abort_stack_hi &&
            size <= mario_abort_stack_hi - address) {
        memcpy(buffer, (void *)(uintptr_t)address, size);
        return 1;
    }
    return 0;
}

static void mario_abort_diag(uint64_t info, uint64_t size, uint64_t sp, uint64_t fp, uint64_t stack_end) {
    mario_abort_stack_lo = sp;
    mario_abort_stack_hi = stack_end;
    int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
    if (fd < 0) LOG("[mario-abort] using syscall/validated stack reader\n");
    uint32_t result;
    if (size >= sizeof result && mario_abort_read(fd, info, &result, sizeof result))
        LOG("[mario-abort] info32=%08x module=%u description=%u\n",
            result, result & 0x1ffu, (result >> 9) & 0x1fffu);
    for (unsigned i = 0; i < 16; i++) {
        uint64_t words[2], at = sp + i * 16ull;
        if (at < sp || !mario_abort_read(fd, at, words, sizeof words)) break;
        LOG("[mario-abort] stack %llx: %016llx %016llx\n",
            (unsigned long long)at, (unsigned long long)words[0], (unsigned long long)words[1]);
    }
    for (unsigned i = 0; i < 16; i++) {
        uint64_t frame[2];
        if ((fp & 15) || !mario_abort_read(fd, fp, frame, sizeof frame)) break;
        LOG("[mario-abort] frame %u fp=%llx lr=%llx\n", i,
            (unsigned long long)fp, (unsigned long long)frame[1]);
        if (frame[0] <= fp || frame[0] - fp > 0x1000000) break;
        fp = frame[0];
    }
    if (fd >= 0) close(fd);
    mario_abort_stack_lo = mario_abort_stack_hi = 0;
}
