// Native Vulkan texture residency / dirty-subresource uploads.
// This module only handles CPU-authored, uncompressed color texels. It never
// owns render targets and never changes guest image formats.
#pragma once
#include "vk.h"
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

bool vk_native_texture_enabled(void);
// True means the function performed (or safely skipped) the upload.
// False means caller must use its original complete-subresource upload.
bool vk_native_texture_upload(TexBackend *b, uint32_t mip, uint32_t layer,
                             uint32_t w, uint32_t h, uint32_t bytes_per_pixel,
                             const uint8_t *pixels, size_t pitch);
void vk_native_texture_discard(TexBackend *b);
void vk_native_texture_stats(char *dst, size_t capacity);
