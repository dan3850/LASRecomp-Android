/* SPDX-License-Identifier: MIT
 * Standalone cache regression only. The Android app never links this file.
 * A test-owned temporary stream replaces /dev/full; short writes and buffered
 * flush failures report ENOSPC without relying on device access or libc's
 * handling of /dev/full. All other files and operations use the real libc.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

FILE* __real_fopen(const char* path, const char* mode);
size_t __real_fwrite(const void* ptr, size_t size, size_t count, FILE* stream);
int __real_fflush(FILE* stream);
int __real_fclose(FILE* stream);

static FILE* full_stream;

static int fail_at(const char* operation) {
    const char* mode = getenv("SNX_TEST_ENOSPC_MODE");
    return mode && !strcmp(mode, operation);
}

FILE* __wrap_fopen(const char* path, const char* mode) {
    if (strcmp(path, "/dev/full")) return __real_fopen(path, mode);
    if (strcmp(mode, "wb")) {
        errno = ENOENT;
        return NULL;
    }
    /* Python runs this binary inside its private TemporaryDirectory. Avoid
       libc tmpfile(), whose default directory can be unwritable on Android. */
    full_stream = __real_fopen("pipeline-enospc-fixture.tmp", "w+b");
    return full_stream;
}

size_t __wrap_fwrite(const void* ptr, size_t size, size_t count, FILE* stream) {
    if (stream == full_stream && size && count && fail_at("write")) {
        fputs("SNX_TEST_ENOSPC_INJECTED=write\n", stderr);
        errno = ENOSPC;
        return 0;
    }
    return __real_fwrite(ptr, size, count, stream);
}

int __wrap_fflush(FILE* stream) {
    if (stream && stream == full_stream && fail_at("flush")) {
        fputs("SNX_TEST_ENOSPC_INJECTED=flush\n", stderr);
        errno = ENOSPC;
        return EOF;
    }
    return __real_fflush(stream);
}

int __wrap_fclose(FILE* stream) {
    if (stream == full_stream) full_stream = NULL;
    return __real_fclose(stream);
}
