// Compile-time Mario boot identity; populated from the already linked library's
// private build report, never from Zelda offsets or a guessed SDK base.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "mario_profile_config.h"

static inline int mario_nso_matches(const char *name, const uint8_t *raw, size_t length) {
    static const uint8_t main_id[32] = MARIO_MAIN_BUILD_ID_BYTES;
    static const uint8_t sdk_id[32] = MARIO_SDK_BUILD_ID_BYTES;
    const uint8_t *id = !strcmp(name, "main") ? main_id : !strcmp(name, "sdk") ? sdk_id : NULL;
    return id && raw && length >= 0x100 && !memcmp(raw, "NSO0", 4) && !memcmp(raw + 0x40, id, 32);
}
