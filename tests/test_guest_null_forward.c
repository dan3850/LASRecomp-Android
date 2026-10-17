// clang -std=gnu11 -O1 -g -Wall -Wextra -Werror
//   -fsanitize=address,undefined -Iruntime tests/test_guest_null_forward.c
//   -o /tmp/test_guest_null_forward && /tmp/test_guest_null_forward
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "../runtime/guest_forward_guard.h"

int main(void) {
    Cpu c = {0};
    uint64_t object[5] = {11, 22, 0, 44, 55};
    c.x[0] = (uint64_t)(uintptr_t)object;
    c.x[2] = 0x1122334455667788ull;
    c.x[30] = 0x70013c229cull;
    c.pc = 0x70010cce50ull;
    assert(rt_guest_nullable_child_return(&c));
    assert(c.x[0] == 0 && c.x[1] == (uint64_t)(uintptr_t)object);
    assert(c.pc == c.x[30] && c.x[2] == 0x1122334455667788ull);

    memset(&c, 0, sizeof c);
    object[2] = 0x70012345678ull;
    c.x[0] = (uint64_t)(uintptr_t)object;
    c.x[30] = 0x70013c229cull;
    c.pc = 0x70010cce50ull;
    assert(!rt_guest_nullable_child_return(&c));
    assert(c.x[0] == (uint64_t)(uintptr_t)object);
    assert(c.pc == 0x70010cce50ull); // original compiled thunk remains active
    assert(c.x[30] == 0x70013c229cull);
    c.pc = 0x70010cce30ull; // sibling forwarding target (vtable+0xA8)
    assert(!rt_guest_nullable_child_return(&c));
    object[2] = 0;
    assert(rt_guest_nullable_child_return(&c));
    assert(c.x[0] == 0 && c.pc == c.x[30]);

    memset(&c, 0, sizeof c);
    c.x[30] = 0x70013c229cull;
    assert(rt_guest_nullable_child_return(&c)); // even a NULL 'this' can't crash
    assert(c.x[0] == 0 && c.x[1] == 0 && c.pc == c.x[30]);
    puts("PASS: nullable forwarding guard skips only missing child");
    return 0;
}
