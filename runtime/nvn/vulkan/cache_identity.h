#pragma once
#if __has_include("vulkan_cache_build_id.h")
#include "vulkan_cache_build_id.h"
#else
// A custom build without a source identity still renders normally. Never
// persist/replay recipes across unidentified, potentially incompatible builds.
#define LAS_VK_CACHE_PERSISTENT 0
#define LAS_VK_CACHE_BUILD_ID __DATE__ " " __TIME__
#endif
