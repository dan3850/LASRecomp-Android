// Registered by libmain.so before starting the separately loaded engine.
// Android may keep JNI libraries local to a linker namespace: do not rely on
// finding libmain's exports through RTLD_DEFAULT from inside the engine.
#pragma once
#include <stddef.h>

typedef int (*LasOpenDocument)(const char *utf8_path);
typedef int (*LasRomfsManifest)(char **out, size_t *length);

#ifdef __cplusplus
extern "C" {
#endif
__attribute__((visibility("default")))
void lasrecomp_android_set_document_bridge(LasOpenDocument open_document, LasRomfsManifest manifest);
#ifdef __cplusplus
}
#endif
