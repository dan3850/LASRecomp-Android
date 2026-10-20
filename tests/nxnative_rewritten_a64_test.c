/* Execute the exact output of rewrite_tls_minimal.py on Android ARM64.
 * Input is a 40-byte generated file; the final 8-byte thunk target is
 * patched to our native TLS getter before mapping the image RX.
 */
#include "android_image.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uintptr_t nx_android_guest_slot_get(unsigned slot);
int nx_android_guest_slot_set(unsigned slot, uintptr_t value);

int main(int argc, char **argv) {
#if !defined(__aarch64__)
    puts("NX_REWRITTEN_A64_SKIP");
    return 0;
#else
    if (argc != 2) { fprintf(stderr, "usage: %s rewritten.bin\n", argv[0]); return 1; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 2; }
    unsigned char code[40];
    size_t n = fread(code, 1, sizeof(code), f);
    int extra = fgetc(f);
    fclose(f);
    if (n != sizeof(code) || extra != EOF) {
        fputs("unexpected rewritten code size\n", stderr);
        return 3;
    }
    /* Verify fixed instructions and placeholder before trusting input. */
    const uint32_t expected[] = {
        0xA9BF7BFDu, 0x52800020u, 0x94000003u, 0xA8C17BFDu,
        0xD65F03C0u, 0x58000070u, 0xD61F0200u, 0xD503201Fu
    };
    uint64_t placeholder;
    memcpy(&placeholder, code + 32, 8);
    if (memcmp(code, expected, sizeof(expected)) != 0 || placeholder != 0) {
        fputs("rewriter output does not match expected instructions\n", stderr);
        return 4;
    }
    uintptr_t target = (uintptr_t)&nx_android_guest_slot_get;
    memcpy(code + 32, &target, sizeof(target));
    if (nx_android_guest_slot_set(1, 0x42) != 0) return 5;
    nx_android_image image = {0};
    if (nx_android_image_alloc(&image, 4096) != 0) return 6;
    if (nx_android_image_copy(&image, 0, code, sizeof(code)) != 0) return 7;
    if (nx_android_image_protect(&image, 0, image.page_size, 1) != 0) return 8;
    __builtin___clear_cache((char *)image.base, (char *)image.base + sizeof(code));
    uintptr_t (*entry)(void) = NULL;
    memcpy(&entry, &image.base, sizeof(entry));
    uintptr_t result = entry();
    nx_android_image_free(&image);
    if (result != 0x42) {
        fprintf(stderr, "NX_REWRITTEN_A64_FAIL result=%#lx\n", (unsigned long)result);
        return 9;
    }
    puts("NX_REWRITTEN_A64_OK value=42");
    return 0;
#endif
}
