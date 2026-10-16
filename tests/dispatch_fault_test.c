// Verify symbol names survive the next lookup's thread-local buffer reuse.
#include <assert.h>
#include <sys/wait.h>
#include "../runtime/dispatch.c"

const char *plat_symbol(uint64_t pc, uint64_t *offset) { (void)pc; (void)offset; return NULL; }
void plat_print_backtrace(void) {}
void plat_fatal_notice(void) { _exit(0); } // stop after reporting, without raising SIGABRT
Cpu *kernel_current_cpu(void) { return NULL; }

int main(void) {
    // Synthetic host addresses avoid compiler/linker-dependent function layout.
    static const uint64_t addrs[] = {0x7001000000, 0x7002000000};
    static const GuestFn fns[] = {(GuestFn)(uintptr_t)0x100000, (GuestFn)(uintptr_t)0x200000};
    tables[0] = (FnTable){.addrs = addrs, .fns = fns, .count = 2};
    int output[2]; assert(!pipe(output));
    pid_t pid = fork(); assert(pid >= 0);
    if (!pid) {
        close(output[0]); dup2(output[1], STDERR_FILENO); close(output[1]);
        rt_fault_report("test", 0, 0x100034, 0x200088);
    }
    close(output[1]);
    char report[2048] = {0}; size_t used = 0; ssize_t n;
    while ((n = read(output[0], report + used, sizeof report - used - 1)) > 0) used += n;
    close(output[0]); int status; assert(waitpid(pid, &status, 0) == pid);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    assert(strstr(report, "host pc 100034 (f_7001000000+34)"));
    assert(strstr(report, "host lr 200088 (f_7002000000+88)"));
    puts("Crash report: distinct PC/LR names and offsets PASS");
}
