// Native Android Vulkan: persistent device-preferred buffers for immutable
// graphics inputs. Multi-version resources cannot be overwritten in-flight.
#pragma once
#include "vk.h"
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

typedef enum { VK_RESIDENT_GEOMETRY = 0, VK_RESIDENT_GMEM = 1 } VkResidentDomain;
typedef bool (*VkResidentEqual)(const uint8_t *shadow, const void *ctx, size_t n);
typedef void (*VkResidentFill)(uint8_t *dst, const void *ctx, size_t n);

typedef struct {
    VkResidentDomain domain;
    uint64_t key;                // bucket hint, NOT a substitute for identity verification
    const void *identity;        // copied and compared byte-for-byte (addresses or packed GMEM plan)
    size_t identity_size;
    size_t size;                 // valid guest bytes, padded to 4 for transfer
    VkResidentEqual equal;       // exact verification against guest data
    VkResidentFill fill;         // fills *all* the bytes of a new version
    const void *context;
} VkResidentRequest;

// Returns a persistent read-only buffer or {0} to fall back to legacy path.
// All methods run on the Vulkan render thread, apart from guest writes that
// the caller has already synchronized using existing preflight logic.
bool vk_resident_enabled(void);
VkSpan vk_resident_get(const VkResidentRequest *req);
void vk_resident_reset(void);     // GPU must be idle before this is called
void vk_resident_stats_append(char *buf, size_t capacity);
