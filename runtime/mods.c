// The prepared library calls this only at the two supported instruction sites.
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>

#include "mods.h"
#include "hle.h"

static _Atomic int mod_enabled = -1;
static _Atomic unsigned applied_sites;
static int library_kind;  // set before guest threads start: 0 original, 1 menu, 2 fixed NOPs
static pthread_mutex_t status_lock = PTHREAD_MUTEX_INITIALIZER;

static void write_status(void) {
    const char *root = getenv("LARECOMP_DATA_ROOT");
    if (!root || root[0] != '/') return;
    char directory[4096], path[4096], temporary[4096];
    int a = snprintf(directory, sizeof directory, "%s/mods", root);
    int b = snprintf(path, sizeof path, "%s/%s", root, LAS_MOD_STATUS_FILE);
    int c = snprintf(temporary, sizeof temporary, "%s.tmp", path);
    if (a < 0 || (size_t)a >= sizeof directory || b < 0 || (size_t)b >= sizeof path ||
        c < 0 || (size_t)c >= sizeof temporary) return;
    pthread_mutex_lock(&status_lock);
    mkdir(directory, 0700);
    FILE *file = fopen(temporary, "wb");
    if (file) {
        unsigned sites = atomic_load(&applied_sites);
        int enabled = atomic_load(&mod_enabled);
        int result = fprintf(file, "Stable 60fps v2\nBiblioteca desta sessão: %s.\n%s\n%s%s%s",
            library_kind == 1 ? "compatível com o menu" : library_kind == 2 ? "mod fixo" : "sem suporte ao mod",
            library_kind == 2 ? "Mod fixo: ativado, sem controle pelo menu." : library_kind == 0 ?
                "O arquivo de seleção não ativa o mod nesta biblioteca." : enabled > 0 ?
                "Seleção carregada: ativada." : "Seleção carregada: desativada.",
            library_kind == 1 && enabled > 0 && !sites ? "Aguardando execução dos pontos do mod.\n" : "",
            sites & 1 ? "NOP executado em main+01019608.\n" : "",
            sites & 2 ? "NOP executado em main+01019628.\n" : "");
        int closed = fclose(file);
        if (result >= 0 && !closed) rename(temporary, path);
        else remove(temporary);
    }
    pthread_mutex_unlock(&status_lock);
}

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

void rt_mod_begin(const char *menu_capability, const char *fixed_build_id) {
    library_kind = menu_capability && !strcmp(menu_capability, LAS_MOD_MENU_CAPABILITY) ? 1 :
        !menu_capability && fixed_build_id && !strcasecmp(fixed_build_id, LAS_MOD_BUILD_ID) ? 2 : 0;
    atomic_store(&applied_sites, 0);
    atomic_store(&mod_enabled, library_kind == 1 ? read_enabled() : library_kind == 2);
    LOG("[mods] Stable 60fps v2: library=%s selected=%d; menu NOPs require executed-site confirmation\n",
        library_kind == 1 ? "menu" : library_kind == 2 ? "fixed" : "unsupported", atomic_load(&mod_enabled));
    write_status();
}

RT_ON_RESET(mods_reset) {
    atomic_store(&mod_enabled, -1);
    atomic_store(&applied_sites, 0);
    if (library_kind) {
        atomic_store(&mod_enabled, library_kind == 1 ? read_enabled() : 1);
        write_status();
    }
}

int rt_mod_nop(uint64_t pc) {
    if (pc != 0x7001019608ull && pc != 0x7001019628ull) return 0;
    int enabled = atomic_load_explicit(&mod_enabled, memory_order_acquire);
    if (enabled < 0) {
        int expected = -1, selected = read_enabled();
        atomic_compare_exchange_strong_explicit(&mod_enabled, &expected, selected,
                                                memory_order_acq_rel, memory_order_acquire);
        enabled = atomic_load_explicit(&mod_enabled, memory_order_acquire);
    }
    if (enabled && library_kind == 1) {
        unsigned bit = pc == 0x7001019608ull ? 1 : 2;
        if (!(atomic_load(&applied_sites) & bit) && !(atomic_fetch_or(&applied_sites, bit) & bit)) {
            LOG("[mods] Stable 60fps v2: NOP executed at main+%08llX\n",
                (unsigned long long)(pc - 0x7000000000ull));
            write_status();
        }
    }
    return enabled;
}
