// cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -O1 tests/test_gmem_delta.c -o /tmp/test_gmem_delta && /tmp/test_gmem_delta
#include "../runtime/nvn/vulkan/gmem_delta.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void test(size_t length, size_t offset) {
    size_t cap = offset + length + 32;
    uint8_t *mapped = malloc(cap), *shadow = malloc(cap), *guest = malloc(length ? length : 1);
    assert(mapped && shadow && guest);
    memset(mapped, 0xa5, cap);
    memset(shadow, 0xa5, cap);
    memset(guest, 0xa5, length);
    GmemDelta d = gmem_delta_copy(mapped, shadow, guest, offset, length);
    assert(d.copied == 0 && d.first == SIZE_MAX && d.end == 0);
    if (length) {
        for (size_t i = 0; i < length; i += 4097) guest[i]++;
        d = gmem_delta_copy(mapped, shadow, guest, offset, length);
        assert(d.first >= offset && d.end <= offset + length && d.copied > 0 && d.copied <= length);
        assert(!memcmp(mapped + offset, guest, length));
        assert(!memcmp(shadow + offset, guest, length));
        assert((!offset || mapped[0] == 0xa5) && mapped[cap - 1] == 0xa5);
        d = gmem_delta_copy(mapped, shadow, guest, offset, length);
        assert(d.copied == 0);
        memset(guest, 0x19, length);
        d = gmem_delta_copy(mapped, shadow, guest, offset, length);
        assert(d.first == offset && d.end == offset + length && d.copied <= length);
        assert(!memcmp(mapped + offset, guest, length));
    }
    free(mapped); free(shadow); free(guest);
}
int main(void) {
    for (size_t n = 0; n < 15000; n += 13)
        for (size_t off = 0; off < 16; off += 3) test(n, off);
    for (size_t n = 65536; n <= 2097152; n *= 2) test(n, 4);
    puts("gmem_delta: PASS");
    return 0;
}
