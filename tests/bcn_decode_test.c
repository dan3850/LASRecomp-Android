#include "../runtime/nvn/bcn_decode.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void red_block(unsigned f, unsigned char b[16]) {
    memset(b, 0, 16);
    unsigned off = f == LAS_BC1 ? 0 : 8;
    if (f == LAS_BC2) memset(b, 0xff, 8);
    if (f == LAS_BC3) b[0] = 255;
    b[off] = 0; b[off + 1] = 0xf8; // RGB565 red; every index selects endpoint 0.
}
static void bits(unsigned char *b, unsigned *at, unsigned value, unsigned n) {
    for (unsigned i = 0; i < n; i++, (*at)++) b[*at / 8] |= ((value >> i) & 1) << (*at % 8);
}
int main(void) {
    unsigned char b[16], out[128];
    for (unsigned f = LAS_BC1; f <= LAS_BC3; f++) {
        red_block(f, b);
        assert(las_bcn_decode(f, b, sizeof b, 4, 4, 1, out, sizeof out));
        for (unsigned i = 0; i < 16; i++) assert(out[4*i] == 255 && out[4*i+1] == 0 && out[4*i+2] == 0 && out[4*i+3] == 255);
    }
    memset(b, 0xff, 8); b[0] = b[1] = 0; b[2] = 1; b[3] = 0;
    assert(las_bcn_decode(LAS_BC1, b, 8, 4, 4, 1, out, sizeof out));
    for (unsigned i = 0; i < 16; i++) assert(out[4*i+3] == 0);
    for (unsigned f = LAS_BC4U; f <= LAS_BC5S; f++) {
        memset(b, 0, 16); b[0] = f == LAS_BC4S || f == LAS_BC5S ? 0x81 : 201; b[8] = 63;
        assert(las_bcn_decode(f, b, sizeof b, 4, 4, 1, out, sizeof out));
        unsigned p = las_bcn_pixel_bytes(f);
        for (unsigned i = 0; i < 16; i++) { assert(out[p*i] == b[0]); if (p == 2) assert(out[p*i+1] == 63); }
    }
    for (unsigned f = LAS_BC6U; f <= LAS_BC6S; f++) {
        memset(b, 0, 16);
        assert(las_bcn_decode(f, b, 16, 4, 4, 1, out, sizeof out));
        for (unsigned i = 0; i < 16; i++) { uint16_t h[4]; memcpy(h, out+8*i, 8); assert(!h[0] && !h[1] && !h[2] && h[3] == 0x3c00); }
    }
    memset(b, 0, 16); unsigned at = 0;
    bits(b, &at, 1u << 6, 7); // BC7 mode 6; identical endpoints (255,1,1,255).
    for (unsigned c = 0; c < 4; c++) for (unsigned e = 0; e < 2; e++) bits(b, &at, c == 0 || c == 3 ? 127 : 0, 7);
    bits(b, &at, 3, 2);
    assert(las_bcn_decode(LAS_BC7, b, 16, 4, 4, 1, out, sizeof out));
    for (unsigned i = 0; i < 16; i++) assert(out[4*i] == 255 && out[4*i+1] == 1 && out[4*i+2] == 1 && out[4*i+3] == 255);
    // Edges, multiple block rows and depth slices; neither input nor output need alignment.
    for (unsigned f = LAS_BC1; f <= LAS_BC7; f++) for (unsigned w = 1; w <= 11; w++) for (unsigned h = 1; h <= 9; h++) {
        unsigned p = las_bcn_pixel_bytes(f), nb = ((w+3)/4)*((h+3)/4)*2*las_bcn_block_bytes(f), np = w*h*2*p;
        unsigned char *src = calloc(nb+1,1), *dst = malloc(np+2);
        assert(src && dst); memset(dst,0xa5,np+2);
        assert(las_bcn_decode(f,src+1,nb,w,h,2,dst+1,np));
        assert(dst[0] == 0xa5 && dst[np+1] == 0xa5);
        memset(dst,0xa5,np+2);
        assert(!las_bcn_decode(f,src+1,nb-1,w,h,2,dst+1,np));
        for (unsigned i=0;i<np+2;i++) assert(dst[i] == 0xa5);
        assert(!las_bcn_decode(f,src+1,nb,w,h,2,dst+1,np-1));
        free(src); free(dst);
    }
    assert(!las_bcn_decode(LAS_BC1,b,16,0,1,1,out,sizeof out));
    assert(!las_bcn_decode(99,b,16,1,1,1,out,sizeof out));
    assert(!las_bcn_decode(LAS_BC6U,b,16,UINT32_MAX,UINT32_MAX,UINT32_MAX,out,sizeof out));
    puts("PASS: BC1-BC7 canonical pixels, signed/HDR channels, 990 cropped multi-slice images, bounds and overflow");
}
