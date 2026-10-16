#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum {
    LAS_BC_NONE, LAS_BC1, LAS_BC2, LAS_BC3, LAS_BC4U, LAS_BC4S,
    LAS_BC5U, LAS_BC5S, LAS_BC6U, LAS_BC6S, LAS_BC7
};
unsigned las_bcn_pixel_bytes(unsigned format);
unsigned las_bcn_block_bytes(unsigned format);
// Linear block rows, then slices. Crops partial edge blocks; never writes padding.
// BC6H produces RGBA16F (alpha 1); BC4/5 preserve signed normalized channels.
bool las_bcn_decode(unsigned format, const void *blocks, size_t block_bytes,
                    uint32_t w, uint32_t h, uint32_t depth, void *pixels, size_t pixel_bytes);
