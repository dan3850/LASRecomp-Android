// Shader compilation and reflection for the Vulkan backend (shaders.c).
#pragma once
#include <stddef.h>

#include "vk.h"

typedef struct { uint32_t set, binding; VkDescriptorType type; } VkBindingInfo;

void vk_shaders_init(void);
uint32_t *vk_glsl_to_spirv(const char *src, int stage, const char *name, size_t *nwords);  // malloc'd, NULL on error
VkShaderModule vk_module(const uint32_t *spv, size_t nwords);
// Reuse the same source-key and on-disk SPIR-V blobs when rebuilding prior Vulkan pipelines at boot.
uint64_t vk_shader_cache_key(const char *src, int stage);
uint32_t *vk_shader_cache_read(uint64_t key, size_t *nwords);  // malloc'd; NULL on miss
// Descriptor bindings declared by a SPIR-V module.
int vk_reflect(const uint32_t *spv, size_t nwords, VkBindingInfo *out, int max);
VkDescriptorSetLayout vk_set_layout(const VkBindingInfo *b, int n, uint32_t set, VkShaderStageFlags stages);
