/* Actual pinned POSIX tracking functions, with injected syscall outcomes. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <linux/fs.h>
#include <linux/userfaultfd.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
/* Test-only Linux 6.7 UAPI, to exercise both newer and older build headers. */
#ifndef PAGEMAP_SCAN
struct page_region { uint64_t start, end, categories; };
struct pm_scan_arg { uint64_t size, flags, start, end, walk_end, vec, vec_len, max_pages,
                             category_inverted, category_mask, category_anyof_mask, return_mask; };
#define PAGEMAP_SCAN _IOWR('f', 16, struct pm_scan_arg)
#define PM_SCAN_WP_MATCHING (1 << 0)
#define PM_SCAN_CHECK_WPASYNC (1 << 1)
#define PAGE_IS_WRITTEN (1 << 1)
#endif
#ifndef UFFD_FEATURE_WP_ASYNC
#define UFFD_FEATURE_WP_ASYNC (1 << 15)
#endif
#ifndef UFFD_FEATURE_WP_UNPOPULATED
#define UFFD_FEATURE_WP_UNPOPULATED (1 << 13)
#endif
#ifndef UFFD_USER_MODE_ONLY
#define UFFD_USER_MODE_ONLY 1
#endif
#if !NATIVE_UAPI
#undef PAGEMAP_SCAN
#undef UFFD_FEATURE_WP_ASYNC
#endif
#define LOG(...) printf(__VA_ARGS__)
#define WARN(...) ((void)0)
static const char* mode;
static unsigned opens, apis, regs, scans, callbacks;
static long fake_syscall(long number, ...) {
    assert(number == SYS_userfaultfd); opens++;
    printf("TRACE syscall %u\n", opens);
    if (!strcmp(mode, "syscall")) { errno = EPERM; return -1; }
    return 40;
}
static int fake_open(const char* path, int flags, ...) {
    assert(!strcmp(path, "/proc/self/pagemap") && (flags & O_CLOEXEC));
    puts("TRACE open_pagemap");
    if (!strcmp(mode, "pagemap")) { errno = EACCES; return -1; }
    return 41;
}
static int fake_close(int fd) { assert(fd == 40); puts("TRACE close"); return 0; }
static long fake_sysconf(int name) { assert(name == _SC_PAGESIZE); return 4096; }
static int fake_ioctl(int fd, unsigned long op, ...) {
    va_list ap; va_start(ap, op); void* p = va_arg(ap, void*); va_end(ap);
    if (op == UFFDIO_API) {
        struct uffdio_api* a = p; assert(fd == 40 && a->api == UFFD_API); apis++;
        printf("TRACE api %llu\n", (unsigned long long)a->features);
        if (!strcmp(mode, "api") || (!strcmp(mode, "minor_fallback") && apis == 1)) { errno = EINVAL; return -1; }
        a->features |= 0x400000; return 0;
    }
    if (op == UFFDIO_REGISTER) {
        struct uffdio_register* r = p; regs++;
        assert(fd == 40 && r->range.start == 0x10000 && r->range.len == 65 * 4096 && r->mode == UFFDIO_REGISTER_MODE_WP);
        puts("TRACE register");
        if (!strcmp(mode, "register") || (!strcmp(mode, "remap") && regs == 2)) { errno = EINVAL; return -1; }
        return 0;
    }
    if (op == UFFDIO_UNREGISTER) { assert(fd == 40); puts("TRACE unregister"); return 0; }
#if NATIVE_UAPI
    if (op == PAGEMAP_SCAN) {
        struct pm_scan_arg* a = p; assert(fd == 41 && a->size == sizeof *a); scans++;
        assert(a->flags == (PM_SCAN_WP_MATCHING | PM_SCAN_CHECK_WPASYNC));
        assert(a->category_mask == PAGE_IS_WRITTEN && a->return_mask == PAGE_IS_WRITTEN);
        puts("TRACE scan");
        if (!strcmp(mode, "scan")) { errno = EIO; return -1; }
        struct page_region* v = (void*)(uintptr_t)a->vec;
        unsigned n = scans == 1 ? 64 : 1;
        for (unsigned i = 0; i < n; i++) v[i] = (struct page_region){a->start + i * 4096, a->start + (i + 1) * 4096, PAGE_IS_WRITTEN};
        a->walk_end = a->start + n * 4096;
        return (int)n;
    }
#endif
    assert(!"unexpected ioctl"); return -1;
}
#define syscall fake_syscall
#define ioctl fake_ioctl
#define open fake_open
#define close fake_close
#define sysconf fake_sysconf
#include "ww_actual.inc"
#undef syscall
#undef ioctl
#undef open
#undef close
#undef sysconf
static void changed(u8* p, u64 n) { assert((uintptr_t)p == 0x10000 + callbacks * 4096 && n == 4096); callbacks++; }
int main(int argc, char** argv) {
    assert(argc == 2); mode = argv[1];
    if (!strcmp(mode, "disabled")) setenv("SNX_NO_WW", "0", 1); /* presence, even "0", is the original policy */
    ww_init((u8*)(uintptr_t)0x10000, 65 * 4096);
    if (!strcmp(mode, "remap")) ww_remapped((u8*)(uintptr_t)0x10000, 65 * 4096);
    int result = plat_ww_scan((u8*)(uintptr_t)0x10000, 65 * 4096, changed);
    printf("RESULT %d %u %d %u %u %u %u\n", result, callbacks, g_pagemap, opens, apis, regs, scans);
#if DIAGNOSTIC
    int saved = errno; snx_ww_report(); assert(saved == errno);
    unsigned printed = snx_ww_printed; snx_ww_report(); assert(printed == snx_ww_printed);
    for (unsigned i = 0; i < 30; i++) snx_ww_note("bounded", 0, 0, 0);
    snx_ww_report(); assert(snx_ww_printed == 16);
#endif
    return 0;
}
