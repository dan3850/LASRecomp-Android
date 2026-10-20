#include "android_image.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    nx_android_image image = {0};
    const unsigned char payload[] = {1, 2, 3, 4};
    assert(nx_android_image_alloc(&image, 8192) == 0);
    assert(image.base != NULL);
    assert(nx_android_image_copy(&image, 0, payload, sizeof(payload)) == 0);
    assert(memcmp(image.base, payload, sizeof(payload)) == 0);
    assert(nx_android_image_copy(&image, image.mapped_size, payload, sizeof(payload)) == -1);
    assert(nx_android_image_protect(&image, 1, image.page_size, 1) == -1);
    assert(nx_android_image_protect(&image, 0, image.page_size, 1) == 0);
    nx_android_image_free(&image);
    assert(image.base == NULL);
    puts("NX_IMAGE_OK");
    return 0;
}
