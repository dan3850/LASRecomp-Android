// Supported code variants in a separately prepared private game library.
#pragma once
#include <stdint.h>

#define LAS_MOD_BUILD_ID "AE16F71E002AF8CB059A9A74C4D90F34BA984892"
#define LAS_MOD_MENU_CAPABILITY "stable60-v2:" LAS_MOD_BUILD_ID ":01019608,01019628"
#define LAS_MOD_ENABLED_FILE "mods/stable60-v2.enabled"

int rt_mod_nop(uint64_t pc);
