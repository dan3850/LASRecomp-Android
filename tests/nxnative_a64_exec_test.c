/* First native AArch64 guest-code smoke test.
 * Execute generated A64 instructions from the Android image mapping.
 * No Switch game assets required. Not a nxnative rewriter integration yet.
 */
#include "android_image.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main(void) {
#if !defined(__aarch64__)
    puts("NX_A64_SKIP: requires ARM64");
    return 0;
#else
    nx_android_image image = {0};
    /* movz w0,#42 ; ret -- little endian AArch64 words */
    const uint32_t code[] = {0x52800540u, 0xD65F03C0u};
    if (nx_android_image_alloc(&image, 4096) != 0) return 1;
    if (nx_android_image_copy(&image, 0, code, sizeof(code)) != 0) return 2;
    if (nx_android_image_protect(&image, 0, image.page_size, 1) != 0) {
        perror("mprotect RX");
        nx_android_image_free(&image);
        return 3;
    }
    __builtin___clear_cache((char *)image.base, (char *)image.base + sizeof(code));
    /* memcpy avoids an ISO C function-pointer/object-pointer cast diagnostic. */
    int (*entry)(void) = NULL;
    _Static_assert(sizeof(entry) == sizeof(image.base), "function pointer size mismatch");
    memcpy(&entry, &image.base, sizeof(entry));
    int value = entry();
    nx_android_image_free(&image);
    assert(value == 42);
    printf("NX_A64_EXEC_OK value=%d\n", value);
    return 0;
#endif
}
