// Supported code variants in a separately prepared private game library.
#pragma once
#include <stdint.h>

#define LAS_MOD_BUILD_ID "AE16F71E002AF8CB059A9A74C4D90F34BA984892"
#define LAS_MOD_MENU_CAPABILITY "stable60-v2:" LAS_MOD_BUILD_ID ":01019608,01019628"
#define LAS_MOD_ENABLED_FILE "mods/stable60-v2.enabled"
#define LAS_MOD_STATUS_FILE "mods/stable60-v2.status.txt"

// True only for a selected menu-compatible or fixed Stable60 library.
// Used by the host 60 Hz presentation limiter, never changes guest logic.
int rt_mod_stable60_active(void);
int rt_mod_nop(uint64_t pc);
void rt_mod_begin(const char *menu_capability, const char *fixed_build_id);
