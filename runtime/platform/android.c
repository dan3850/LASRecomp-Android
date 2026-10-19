// Native Android host layer for the original LASRecomp runtime.
// This is not a Termux executable. Linked into the APK's own arm64-v8a library.
// Game-code generation still needs an Android-compatible toolchain before it can run in-app.
#define _GNU_SOURCE
#include <android/log.h>
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/ucontext.h>
#include <time.h>
#include <unistd.h>

#include "../platform.h"
#include "android_documents.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif
#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "LASRecomp", __VA_ARGS__)
#define ERROR(...) __android_log_print(ANDROID_LOG_ERROR, "LASRecomp", __VA_ARGS__)

// The original guest uses fixed virtual addresses. Never use MAP_FIXED to claim
// the initial range: that could overwrite Android's own mappings.
bool plat_reserve_guest(uint64_t lo, uint64_t hi) {
    if (lo >= hi || (lo & (PLAT_PAGE - 1)) || (hi & (PLAT_PAGE - 1))) return false;
    size_t len = (size_t)(hi - lo);
    void *p = mmap((void *)(uintptr_t)lo, len, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_FIXED_NOREPLACE, -1, 0);
    if (p == MAP_FAILED) {
        ERROR("Cannot reserve guest address space %llx-%llx: %s",
              (unsigned long long)lo, (unsigned long long)hi, strerror(errno));
        return false;
    }
    if (p != (void *)(uintptr_t)lo) {
        munmap(p, len);
        ERROR("Guest memory mapped at unexpected address");
        return false;
    }
    return true;
}

bool plat_reset_guest(uint64_t lo, uint64_t hi) {
    // Only used after the original range was successfully reserved.
    return lo < hi && mmap((void *)(uintptr_t)lo, (size_t)(hi - lo),
                           PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_FIXED,
                           -1, 0) == (void *)(uintptr_t)lo;
}

void plat_commit(uint64_t addr, uint64_t size) { (void)addr; (void)size; }
int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {
    (void)addr; (void)size; (void)pages; (void)max; (void)page;
    return -1;  // Android does not expose Windows-style write tracking.
}
int plat_protect(uint64_t addr, uint64_t size, int prot) {
    int flags = prot == PLAT_PROT_NONE ? PROT_NONE :
                prot == PLAT_PROT_READ ? PROT_READ : PROT_READ | PROT_WRITE;
    return mprotect((void *)(uintptr_t)addr, (size_t)size, flags);
}

uint64_t plat_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

void plat_sleep_until_ns(uint64_t t) {
    struct timespec ts = { .tv_sec = (time_t)(t / 1000000000ull),
                           .tv_nsec = (long)(t % 1000000000ull) };
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR) {}
}

// The upstream P/E core selection is Windows-only. On Android use a soft nice
// preference for the critical threads, and let the system choose the CPU core.
// A privileged scheduling policy or hard affinity is deliberately not attempted.
// LARECOMP_ANDROID_PERF_THREADS=0 disables the new hints for an A/B comparison.
void plat_thread_perf_core(int role) {
    static const char *const names[] = {"game", "render", "vsync"};
    if (role < PLAT_PERF_GAME || role > PLAT_PERF_VSYNC) return;
    const char *opt = getenv("LARECOMP_ANDROID_PERF_THREADS");
    if (opt && strcmp(opt, "0") == 0) {
        LOG("[perf-thread] %s disabled tid=%ld cpu=%d\n",
            names[role], (long)gettid(), sched_getcpu());
        return;
    }

    const int target_nice = -4; // same conservative request as the existing VI hint
    int before = getpriority(PRIO_PROCESS, 0); // Android/Linux: current native thread
    int status = 0, saved_errno = 0;
    if (before > target_nice && setpriority(PRIO_PROCESS, 0, target_nice) != 0) {
        status = -1;
        saved_errno = errno; // Android may refuse negative nice without privilege
    }
    int after = getpriority(PRIO_PROCESS, 0);
    LOG("[perf-thread] %s tid=%ld cpu=%d nice=%d->%d target=%d status=%s errno=%d\n",
        names[role], (long)gettid(), sched_getcpu(), before, after,
        target_nice, status ? "denied" : "ok", saved_errno);
}

void plat_thread_realtime(uint64_t period_ns) {
    (void)period_ns;
    // Preserve the pre-existing VI scheduling request in both A/B modes.
    (void)setpriority(PRIO_PROCESS, 0, -4);
    plat_thread_perf_core(PLAT_PERF_VSYNC);
}

// Same AdrenoTools feature used by Eden/yuzu on Android. KGSL_PWRCTRL
// requests maximum clocks but does not bypass Android thermal policies.
// A status of true means the library was called, not that the requested
// frequency was achieved (AdrenoTools' API returns void).
static void (*adreno_turbo_call)(bool);
static int adreno_turbo_active;
static void adreno_turbo_restore(void) {
    if (adreno_turbo_active && adreno_turbo_call) {
        adreno_turbo_call(false);
        adreno_turbo_active = 0;
        LOG("[adreno-turbo] clock request disabled on exit\n");
    }
}
bool plat_adreno_turbo_set(bool enabled) {
    if ((int)enabled == adreno_turbo_active) return true;
    if (enabled && !adreno_turbo_call) {
        int fd = open("/dev/kgsl-3d0", O_RDWR | O_CLOEXEC);
        if (fd < 0) {
            LOG("[adreno-turbo] unavailable: /dev/kgsl-3d0 (%s)\n", strerror(errno));
            return false;
        }
        close(fd);
        void *lib = dlopen("libadrenotools.so", RTLD_NOW | RTLD_LOCAL);
        if (!lib) {
            LOG("[adreno-turbo] libadrenotools unavailable: %s\n", dlerror());
            return false;
        }
        adreno_turbo_call = (void (*)(bool))dlsym(lib, "adrenotools_set_turbo");
        if (!adreno_turbo_call) {
            LOG("[adreno-turbo] adrenotools_set_turbo unavailable\n");
            dlclose(lib);
            return false;
        }
        // Held until process exit because we keep the function pointer.
        (void)atexit(adreno_turbo_restore);
    }
    if (adreno_turbo_call) {
        adreno_turbo_call(enabled);
        adreno_turbo_active = enabled ? 1 : 0;
        LOG("[adreno-turbo] requested=%s (actual clock subject to KGSL and thermal policy)\n",
            enabled ? "on" : "off");
    }
    return true;
}

void plat_init(void) {
    // Android's app-private directory is supplied by the Activity when calling
    // lasrecomp_android_start(); no Termux environment variables are consulted.
    const char *dir = getenv("LARECOMP_DATA_ROOT");
    if (!dir || *dir != '/') {
        ERROR("Android app data directory not configured");
        return;
    }
    char path[2048];
    if (snprintf(path, sizeof path, "%s/lasrecomp.log", dir) >= (int)sizeof path) return;
    FILE *f = fopen(path, "a");
    if (f) {
        (void)dup2(fileno(f), STDERR_FILENO);
        (void)dup2(fileno(f), STDOUT_FILENO);
        fclose(f);
    }
    LOG("Android runtime initialized; data=%s", dir);
}

bool plat_exe_path(char *buf, size_t size) {
    // /proc/self/exe is app_process64, NOT our APK's native library.
    if (size) buf[0] = 0;
    return false;
}
void plat_exec(char *const argv[]) {
    // Android app processes must not re-exec app_process or a native binary.
    (void)argv;
    errno = ENOTSUP;
}
void plat_terminate(void) { _exit(0); }

const char *plat_symbol(uint64_t pc, uint64_t *offset) {
    Dl_info info = {0};
    if (!dladdr((void *)(uintptr_t)pc, &info) || !info.dli_sname) return NULL;
    if (offset) *offset = pc - (uint64_t)(uintptr_t)info.dli_saddr;
    return info.dli_sname;
}
void plat_print_backtrace(void) {
    // A full Android unwind implementation can be added independently of boot.
    ERROR("Runtime backtrace requested; see the Android tombstone for native frames");
}
void plat_fatal_notice(void) {
    fflush(stderr);
    ERROR("LASRecomp stopped; see the app-private lasrecomp.log");
}

static void crash_handler(int sig, siginfo_t *si, void *ctx) {
    const ucontext_t *uc = (const ucontext_t *)ctx;
    uint64_t addr = (uint64_t)(uintptr_t)si->si_addr;
    uint64_t pc = uc->uc_mcontext.pc;
    uint64_t lr = uc->uc_mcontext.regs[30];
    if (rt_fault_watch(addr, pc)) return;
    char msg[32];
    snprintf(msg, sizeof msg, "signal %d", sig);
    rt_fault_report(msg, addr, pc, lr);
}
void plat_crash_handler_install(void) {
    stack_t ss = { .ss_sp = malloc(1 << 20), .ss_size = 1 << 20 };
    if (!ss.ss_sp || sigaltstack(&ss, NULL)) return;
    struct sigaction sa = {0};
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);
    sigaction(SIGFPE, &sa, NULL);
}

// The desktop launcher runs external Python/clang subprocesses to generate
// lasgame.so. Android cannot rely on a Termux binary; reject this explicitly
// until an in-app generator/compiler is integrated.
PlatProc plat_spawn(const char *const argv[], const char *log_path, bool append_log) {
    (void)argv; (void)log_path; (void)append_log;
    errno = ENOTSUP;
    ERROR("External compiler/process unavailable inside standalone APK");
    return 0;
}
int plat_proc_wait(PlatProc p, bool block) { (void)p; (void)block; return 255; }
void plat_proc_kill(PlatProc p) { (void)p; }

static bool remove_tree(const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0) return false;
    if (!S_ISDIR(st.st_mode)) return unlink(path) == 0;
    DIR *d = opendir(path);
    if (!d) return false;
    bool ok = true;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char child[4096];
        int n = snprintf(child, sizeof child, "%s/%s", path, e->d_name);
        if (n < 0 || n >= (int)sizeof child || !remove_tree(child)) { ok = false; break; }
    }
    closedir(d);
    return ok && rmdir(path) == 0;
}
bool plat_remove_tree(const char *dir) { return dir && remove_tree(dir); }

static LasOpenDocument game_open_document;
static LasRomfsManifest game_romfs_manifest;

void lasrecomp_android_set_document_bridge(LasOpenDocument open_document, LasRomfsManifest manifest) {
    game_open_document = open_document;
    game_romfs_manifest = manifest;
}

/* The returned descriptor is owned by the caller. No content URI is a path. */
int lasrecomp_external_open(const char *relative_path) {
    if (!relative_path || relative_path[0] == '/') { errno = EINVAL; return -1; }
    if (!game_open_document) { errno = ENOSYS; return -1; }
    return game_open_document(relative_path);
}

int lasrecomp_external_romfs_manifest(char **out, size_t *length) {
    if (!game_romfs_manifest) { errno = ENOSYS; return -1; }
    return game_romfs_manifest(out, length);
}
