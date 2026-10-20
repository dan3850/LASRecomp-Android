/* Experimental Linux/Android guest image mapping; not yet wired into nxnative. */
#define _GNU_SOURCE
#include "android_image.h"
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static int align_up(size_t n, size_t p, size_t *out) {
    if (!p || n > SIZE_MAX - (p - 1)) return -1;
    *out = (n + p - 1) / p * p; return 0;
}
int nx_android_image_alloc(nx_android_image *out, size_t size) {
    if (!out || !size) return -1;
    memset(out, 0, sizeof(*out));
    long p = sysconf(_SC_PAGESIZE);
    if (p <= 0) return -1;
    size_t len;
    if (align_up(size, (size_t)p, &len)) return -1;
    void *ptr = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (ptr == MAP_FAILED) return -1;
    out->base = ptr; out->mapped_size = len; out->page_size = (size_t)p;
    return 0;
}
int nx_android_image_copy(nx_android_image *img, size_t off, const void *src, size_t n) {
    if (!img || !img->base || (!src && n) ||
        off > img->mapped_size || n > img->mapped_size - off) return -1;
    if (n) memcpy((char *)img->base + off, src, n);
    return 0;
}
int nx_android_image_protect(nx_android_image *img, size_t off, size_t n, int executable) {
    if (!img || !img->base || !n || off % img->page_size ||
        off > img->mapped_size || n > img->mapped_size - off) return -1;
    size_t len;
    if (align_up(n, img->page_size, &len) || len > img->mapped_size - off) return -1;
    return mprotect((char *)img->base + off, len,
                    executable ? (PROT_READ | PROT_EXEC) : PROT_READ);
}
void nx_android_image_free(nx_android_image *img) {
    if (!img) return;
    if (img->base) munmap(img->base, img->mapped_size);
    memset(img, 0, sizeof(*img));
}
