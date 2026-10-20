// Mario-only: minimal Switch HID NpadFullKey / NpadSystemExt shared memory.
// Fixed offsets follow switchbrew HID SharedMemoryFormat (0x40000 bytes).
// No Nintendo SDK code or game assets are included.
#ifndef LASRECOMP_MARIO_HID_NPAD_H
#define LASRECOMP_MARIO_HID_NPAD_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum {
    MARIO_HID_MEMORY_BYTES = 0x40000,
    MARIO_HID_PLAYER1 = 0x9a00,
    MARIO_HID_FULLKEY = 0x28,
    MARIO_HID_SYSTEM_EXT = 0x1408,
    MARIO_HID_ENTRY_SIZE = 0x30,
    MARIO_HID_RING_CAPACITY = 17,
};

static inline void mario_hid_put32(uint8_t *p, size_t off, uint32_t n) {
    memcpy(p + off, &n, sizeof n);
}
static inline void mario_hid_put64(uint8_t *p, size_t off, uint64_t n) {
    memcpy(p + off, &n, sizeof n);
}
static inline void mario_hid_ring_sample(uint8_t *p, size_t ring,
                                          uint64_t sequence, uint64_t buttons,
                                          int32_t lx, int32_t ly, int32_t rx, int32_t ry) {
    uint64_t tail = (sequence - 1u) % MARIO_HID_RING_CAPACITY;
    const size_t state = ring + 0x20 + (size_t)tail * MARIO_HID_ENTRY_SIZE;
    // Write the sample first; the ring header is published last.
    mario_hid_put64(p, state, sequence);          // Atomic storage sequence
    mario_hid_put64(p, state + 0x08, sequence);   // Npad state sampling number
    mario_hid_put64(p, state + 0x10, buttons);
    mario_hid_put32(p, state + 0x18, (uint32_t)lx);
    mario_hid_put32(p, state + 0x1c, (uint32_t)ly);
    mario_hid_put32(p, state + 0x20, (uint32_t)rx);
    mario_hid_put32(p, state + 0x24, (uint32_t)ry);
    mario_hid_put32(p, state + 0x28, 1);         // IsConnected
    mario_hid_put32(p, state + 0x2c, 0);
    mario_hid_put64(p, ring + 0x08, MARIO_HID_RING_CAPACITY);
    mario_hid_put64(p, ring + 0x10, tail);
    mario_hid_put64(p, ring + 0x18,
                    sequence < MARIO_HID_RING_CAPACITY ? sequence : MARIO_HID_RING_CAPACITY);
}

static inline void mario_hid_npad_publish(void *memory, size_t bytes,
                                           uint64_t sequence, uint64_t buttons,
                                           int32_t lx, int32_t ly, int32_t rx, int32_t ry) {
    if (!memory || bytes < MARIO_HID_MEMORY_BYTES || !sequence) return;
    uint8_t *p = memory;
    // Only player 1 is connected; do not fabricate seven extra controllers.
    mario_hid_put32(p, MARIO_HID_PLAYER1, 1);              // NpadFullKey style
    mario_hid_put32(p, MARIO_HID_PLAYER1 + 4, 0);          // Dual assignment
    mario_hid_put32(p, MARIO_HID_PLAYER1 + 0x4188, 1);     // FullKey device type
    mario_hid_ring_sample(p, MARIO_HID_PLAYER1 + MARIO_HID_FULLKEY,
                          sequence, buttons, lx, ly, rx, ry);
    mario_hid_ring_sample(p, MARIO_HID_PLAYER1 + MARIO_HID_SYSTEM_EXT,
                          sequence, buttons, lx, ly, rx, ry);
}
#endif
