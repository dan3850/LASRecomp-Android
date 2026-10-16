// Host movie/texture consumers share the guest's mounted RomFS backend.
#pragma once
#include "platform.h"
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef struct { uint64_t offset, size; bool original; } RomfsAsset;
// original bypasses seed overlays (texture matching needs the original bytes).
bool romfs_asset_open(const char *relative_path, bool original, RomfsAsset *asset);
// File-relative read; short only at EOF. Invalid or inaccessible data is -1.
ssize_t romfs_asset_read(const RomfsAsset *asset, void *dst, size_t size, uint64_t offset);
#ifdef __cplusplus
}
#endif
