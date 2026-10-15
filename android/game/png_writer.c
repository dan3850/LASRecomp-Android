/* Android PNG screenshot writer for LASRecomp's actual Vulkan renderer.
 * Uses Android's system zlib; output is a standard RGBA PNG.
 * Not a substitute for the Vulkan renderer itself.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <zlib.h>

static void be32(unsigned char *dst, uint32_t v) {
    dst[0] = (unsigned char)(v >> 24);
    dst[1] = (unsigned char)(v >> 16);
    dst[2] = (unsigned char)(v >> 8);
    dst[3] = (unsigned char)v;
}

static bool chunk(FILE *f, const char name[4], const unsigned char *data, uint32_t size) {
    unsigned char n[4], checksum[4];
    be32(n, size);
    uLong crc = crc32(0L, Z_NULL, 0);
    crc = crc32(crc, (const Bytef *)name, 4);
    if (size) crc = crc32(crc, data, size);
    be32(checksum, (uint32_t)crc);
    return fwrite(n, 1, 4, f) == 4 &&
           fwrite(name, 1, 4, f) == 4 &&
           (!size || fwrite(data, 1, size, f) == size) &&
           fwrite(checksum, 1, 4, f) == 4;
}

bool las_android_save_png_rgba(const char *path, const uint8_t *rgba, uint32_t w, uint32_t h) {
    if (!path || !rgba || !w || !h || w > (UINT32_MAX / 4)) return false;
    size_t pitch = (size_t)w * 4;
    if (h > SIZE_MAX / (pitch + 1)) return false;
    size_t stride = pitch + 1;
    size_t raw_len = stride * h;
    if ((uint64_t)raw_len > ULONG_MAX) return false;

    unsigned char *raw = malloc(raw_len);
    if (!raw) return false;
    for (uint32_t y = 0; y < h; y++) {
        unsigned char *row = raw + (size_t)y * stride;
        row[0] = 0; // PNG filter type NONE
        memcpy(row + 1, rgba + (size_t)y * pitch, pitch);
    }

    uLongf compressed_cap = compressBound((uLong)raw_len);
    if (compressed_cap > UINT32_MAX) { free(raw); return false; }
    unsigned char *compressed = malloc((size_t)compressed_cap);
    if (!compressed) { free(raw); return false; }
    int z = compress2(compressed, &compressed_cap, raw, (uLong)raw_len, Z_BEST_SPEED);
    free(raw);
    if (z != Z_OK || compressed_cap > UINT32_MAX) { free(compressed); return false; }

    FILE *f = fopen(path, "wb");
    if (!f) { free(compressed); return false; }

    static const unsigned char signature[8] = {137, 80, 78, 71, 13, 10, 26, 10};
    unsigned char hdr[13] = {0};
    be32(hdr, w);
    be32(hdr + 4, h);
    hdr[8] = 8; // RGBA8
    hdr[9] = 6; // truecolor + alpha
    bool ok = fwrite(signature, 1, 8, f) == 8 &&
              chunk(f, "IHDR", hdr, sizeof hdr) &&
              chunk(f, "IDAT", compressed, (uint32_t)compressed_cap) &&
              chunk(f, "IEND", NULL, 0);
    free(compressed);
    if (fclose(f) != 0) ok = false;
    if (!ok) remove(path);
    return ok;
}
