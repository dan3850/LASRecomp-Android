#ifndef NXNATIVE_ANDROID_IMAGE_H
#define NXNATIVE_ANDROID_IMAGE_H
#include <stddef.h>
typedef struct { void *base; size_t mapped_size; size_t page_size; } nx_android_image;
int nx_android_image_alloc(nx_android_image *out, size_t size);
int nx_android_image_copy(nx_android_image *image, size_t offset, const void *src, size_t size);
int nx_android_image_protect(nx_android_image *image, size_t offset, size_t size, int executable);
void nx_android_image_free(nx_android_image *image);
#endif
