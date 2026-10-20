/* Synthetic Switch-style AArch64 TLS read rewritten for Android.
 * Original guest: mrs x0, tpidr_el0; ret
 * Rewritten guest: mov w0,#1; bl nx_android_guest_slot_get; ret
 * We place an AArch64 BL to a local thunk within the mapped code page;
 * thunk uses an absolute function pointer embedded in that same page.
 * This is a focused ABI test, NOT a general NSO rewriting pipeline.
 */
#include "android_image.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

uintptr_t nx_android_guest_slot_get(unsigned slot);
int nx_android_guest_slot_set(unsigned slot, uintptr_t value);

int main(void) {
#if !defined(__aarch64__)
    puts("NX_A64_TLS_SKIP");
    return 0;
#else
    nx_android_image image = {0};
    /* save LR ; mov w0,#1 ; bl thunk ; restore LR ; ret ; thunk ; pointer */
    uint32_t instructions[] = {
        0xA9BF7BFDu, /* stp x29,x30,[sp,#-16]! */
        0x52800020u, /* mov w0, #1 (KTLS) */
        0x94000003u, /* bl to local thunk, 12 bytes ahead */
        0xA8C17BFDu, /* ldp x29,x30,[sp],#16 */
        0xD65F03C0u, /* ret */
        0x58000070u, /* ldr x16, [pc,#12] */
        0xD61F0200u, /* br x16 */
        0xD503201Fu, /* padding */
        0, 0
    };
    uintptr_t target = (uintptr_t)&nx_android_guest_slot_get;
    memcpy((char *)instructions + 32, &target, sizeof(target));
    if (nx_android_guest_slot_set(1, 0x42) != 0) return 1;
    if (nx_android_image_alloc(&image, 4096) != 0) return 2;
    if (nx_android_image_copy(&image, 0, instructions, sizeof(instructions)) != 0) return 3;
    if (nx_android_image_protect(&image, 0, image.page_size, 1) != 0) return 4;
    __builtin___clear_cache((char *)image.base, (char *)image.base + sizeof(instructions));
    uintptr_t (*entry)(void) = NULL;
    memcpy(&entry, &image.base, sizeof(entry));
    uintptr_t value = entry();
    nx_android_image_free(&image);
    if (value != 0x42) {
        fprintf(stderr, "NX_A64_TLS_FAIL value=%#lx\n", (unsigned long)value);
        return 5;
    }
    puts("NX_A64_TLS_OK value=42");
    return 0;
#endif
}
