// Build and run on Termux as part of the Mario update, no game data required.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mario_hid_npad.h"

static uint8_t shared[MARIO_HID_MEMORY_BYTES];
static uint32_t load32(size_t off) {
    uint32_t x; memcpy(&x, shared + off, sizeof x); return x;
}
static uint64_t load64(size_t off) {
    uint64_t x; memcpy(&x, shared + off, sizeof x); return x;
}
#define CHECK(e) do { if (!(e)) { fprintf(stderr, "HID test fail: %s\n", #e); exit(1); } } while (0)

int main(void) {
    const size_t base = MARIO_HID_PLAYER1;
    const size_t full = base + MARIO_HID_FULLKEY;
    const size_t ext = base + MARIO_HID_SYSTEM_EXT;
    mario_hid_npad_publish(shared, sizeof shared, 1, 1u << 10, 12, -21, 33, -44);
    CHECK(load32(base) == 1);
    CHECK(load32(base + 0x4188) == 1);
    CHECK(load32(base + 0x5000) == 0);            // P2 remains disconnected
    CHECK(load64(full + 8) == 17);
    CHECK(load64(full + 0x10) == 0);
    CHECK(load64(full + 0x18) == 1);
    CHECK(load64(full + 0x20) == 1);
    CHECK(load64(full + 0x28) == 1);
    CHECK(load64(full + 0x30) == (1u << 10));
    CHECK(load32(full + 0x38) == 12);
    CHECK(load32(full + 0x3c) == (uint32_t)-21);
    CHECK(load32(full + 0x48) == 1);
    CHECK(load64(ext + 0x30) == (1u << 10));
    for (uint64_t seq = 2; seq <= 35; ++seq)
        mario_hid_npad_publish(shared, sizeof shared, seq, seq, (int32_t)seq, 0, 0, 0);
    CHECK(load64(full + 0x18) == 17);
    CHECK(load64(full + 0x10) == 0);
    CHECK(load64(full + 0x20) == 35);
    CHECK(load64(full + 0x30) == 35);
    CHECK(load64(ext + 0x20) == 35);
    // Rejected undersized buffer must not modify bytes.
    uint8_t small[8] = {0};
    mario_hid_npad_publish(small, sizeof small, 1, 1, 0, 0, 0, 0);
    CHECK(small[0] == 0);
    puts("Mario HID Npad ring: PASS");
    return 0;
}
