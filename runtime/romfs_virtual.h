// Read-only RomFS image backed by the original files, not a generated image.
#pragma once
#include "platform.h"
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RomfsVirtual RomfsVirtual;
// path is UTF-8, relative to romfs/. Return an owned, seekable fd or -1 with errno.
typedef int (*RomfsOpenFile)(void *context, const char *path);

// UTF-8 manifest: D<TAB>path<LF> or F<TAB>decimal-size<TAB>path<LF>.
// Directories (including empty ones) are explicit; root is implicit. Only the
// manifest, tables and file extents are retained. No file contents are copied.
RomfsVirtual *romfs_virtual_create(const char *manifest, size_t length,
                                  RomfsOpenFile open_file, void *context,
                                  char *why, size_t why_size);
uint64_t romfs_virtual_size(const RomfsVirtual *romfs);
// Exact read, including synthetic zero alignment. Errors never become zero data.
ssize_t romfs_virtual_read(RomfsVirtual *romfs, void *dst, size_t size, uint64_t offset);
void romfs_virtual_close(RomfsVirtual *romfs);

#ifdef __cplusplus
}
#endif
