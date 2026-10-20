/* Android AArch64 ABI bridge for nxnative guest thread slots.
 *
 * Rewritten guest instructions must call these helpers through an AArch64
 * trampoline that preserves all live guest registers. This file alone does
 * NOT make Apple's tpidrro_el0-based rewrite safe on Android.
 *
 * Slots are independent per Linux thread and do not depend on bionic's
 * pthread key layout, x18, or the platform TLS register layout.
 */
#include <stdint.h>
#include <stddef.h>

enum { NX_GUEST_X18 = 0, NX_GUEST_TPIDR = 1, NX_GUEST_TPIDRRO = 2,
       NX_GUEST_GATE = 3, NX_GUEST_SLOT_COUNT = 4 };

static _Thread_local uintptr_t nx_guest_slots[NX_GUEST_SLOT_COUNT];

uintptr_t nx_android_guest_slot_get(unsigned slot) {
    return slot < NX_GUEST_SLOT_COUNT ? nx_guest_slots[slot] : 0;
}

int nx_android_guest_slot_set(unsigned slot, uintptr_t value) {
    if (slot >= NX_GUEST_SLOT_COUNT) return -1;
    nx_guest_slots[slot] = value;
    return 0;
}

void nx_android_guest_slot_reset(void) {
    for (unsigned i = 0; i < NX_GUEST_SLOT_COUNT; ++i) nx_guest_slots[i] = 0;
}
