// The prepared library calls this only at the two supported instruction sites.
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#include "mods.h"
#include "hle.h"

static _Atomic int mod_enabled = -1;

static int read_enabled(void) {
    const char *root = getenv("LARECOMP_DATA_ROOT");
    if (!root || root[0] != '/') return 0;
    char path[4096], value[96];
    int n = snprintf(path, sizeof path, "%s/%s", root, LAS_MOD_ENABLED_FILE);
    if (n < 0 || (size_t)n >= sizeof path) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    size_t size = fread(value, 1, sizeof value, file);
    bool valid = !ferror(file) && size < sizeof value;
    fclose(file);
    while (size && (value[size - 1] == '\n' || value[size - 1] == '\r')) --size;
    valid = valid && size == strlen(LAS_MOD_BUILD_ID) && !memcmp(value, LAS_MOD_BUILD_ID, size);
    if (valid) LOG("[mods] Stable 60fps v2 enabled in the menu-compatible game library\n");
    return valid;
}

RT_ON_RESET(mods_reset) { atomic_store(&mod_enabled, -1); }

int rt_mod_nop(uint64_t pc) {
    if (pc != 0x7001019608ull && pc != 0x7001019628ull) return 0;
    int enabled = atomic_load_explicit(&mod_enabled, memory_order_acquire);
    if (enabled < 0) {
        int expected = -1, selected = read_enabled();
        atomic_compare_exchange_strong_explicit(&mod_enabled, &expected, selected,
                                                memory_order_acq_rel, memory_order_acquire);
        enabled = atomic_load_explicit(&mod_enabled, memory_order_acquire);
    }
    return enabled;
}
