// Nullable virtual forwarding for Zelda v1.0.0 guest thunks\n// f_70010cce30 and f_70010cce50.
// Normal dispatch is unchanged. Only a NULL child at this+0x10 causes
// a no-op return instead of dereferencing the NULL child as a vtable.
// This is a guest lifecycle mitigation; it does not manufacture an object.
#pragma once
#include <stdbool.h>
#include "cpu.h"

static inline bool rt_guest_nullable_child_return(Cpu *c) {
    const uint64_t object = c->x[0];
    if (object && LD64(object + 0x10) != 0) return false;
    c->x[1] = object;  // the original thunk preserves its 'this' in guest x1
    c->x[0] = 0;       // no child -> no callback result
    c->pc = c->x[30]; // guest return address, if the caller consults it
    return true;
}
