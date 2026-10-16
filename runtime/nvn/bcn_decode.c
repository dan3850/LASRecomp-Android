#include "bcn_decode.h"
#include <limits.h>
#include <string.h>
#define BCDEC_BC4BC5_PRECISE
#define BCDEC_STATIC
#define BCDEC_IMPLEMENTATION
#include "../../third_party/bcdec/bcdec.h"

unsigned las_bcn_pixel_bytes(unsigned f) {
    if (f == LAS_BC4U || f == LAS_BC4S) return 1;
    if (f == LAS_BC5U || f == LAS_BC5S) return 2;
    if (f == LAS_BC6U || f == LAS_BC6S) return 8;
    return f >= LAS_BC1 && f <= LAS_BC7 ? 4 : 0;
}
unsigned las_bcn_block_bytes(unsigned f) {
    if (!las_bcn_pixel_bytes(f)) return 0;
    return f == LAS_BC1 || f == LAS_BC4U || f == LAS_BC4S ? 8 : 16;
}
static bool product(size_t a, size_t b, size_t *out) {
    if (b && a > SIZE_MAX / b) return false;
    *out = a * b; return true;
}
bool las_bcn_decode(unsigned f, const void *blocks, size_t nb, uint32_t w, uint32_t h,
                    uint32_t depth, void *pixels, size_t np) {
    unsigned bpp = las_bcn_pixel_bytes(f), bpb = las_bcn_block_bytes(f);
    if (!bpp || !blocks || !pixels || !w || !h || !depth) return false;
    size_t bw = w / 4 + (w % 4 != 0), bh = h / 4 + (h % 4 != 0), need, rows, pitch;
    if (!product(bw, bh, &need) || !product(need, depth, &need) ||
        !product(need, bpb, &need) || nb < need ||
        !product(w, bpp, &pitch) || !product(h, depth, &rows) ||
        !product(pitch, rows, &need) || np < need) return false;
    const uint8_t *src = blocks;
    uint8_t *dst = pixels;
    for (uint32_t z = 0; z < depth; z++) for (size_t by = 0; by < bh; by++) for (size_t bx = 0; bx < bw; bx++) {
        union { uint8_t bytes[128]; uint16_t halves[64]; } tile;
        uint16_t rgb[48];
        switch (f) {
        case LAS_BC1: bcdec_bc1(src, tile.bytes, 16); break;
        case LAS_BC2: bcdec_bc2(src, tile.bytes, 16); break;
        case LAS_BC3: bcdec_bc3(src, tile.bytes, 16); break;
        case LAS_BC4U: case LAS_BC4S: bcdec_bc4(src, tile.bytes, 4, f == LAS_BC4S); break;
        case LAS_BC5U: case LAS_BC5S: bcdec_bc5(src, tile.bytes, 8, f == LAS_BC5S); break;
        case LAS_BC6U: case LAS_BC6S:
            bcdec_bc6h_half(src, rgb, 12, f == LAS_BC6S);
            for (unsigned i = 0; i < 16; i++) {
                memcpy(tile.halves + 4 * i, rgb + 3 * i, 6);
                tile.halves[4 * i + 3] = 0x3c00;
            }
            break;
        case LAS_BC7: bcdec_bc7(src, tile.bytes, 16); break;
        default: return false;
        }
        src += bpb;
        size_t nx = w - bx * 4 < 4 ? w - bx * 4 : 4;
        size_t ny = h - by * 4 < 4 ? h - by * 4 : 4;
        for (size_t y = 0; y < ny; y++)
            memcpy(dst + ((size_t)z * h + by * 4 + y) * pitch + bx * 4 * bpp,
                   tile.bytes + y * 4 * bpp, nx * bpp);
    }
    return true;
}
