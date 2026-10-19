// Loads the recompiled game code library (runtime/gamelib.h).
#include "gamelib.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __ANDROID__
#include <sys/stat.h>
#include <limits.h>
#endif
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include "paths.h"
#include "rt.h"
#include "mods.h"

static const GameLibTables *g_tables;
static char g_error[256];

// The library's id file (<library>.id, written next to it by the build): its GAMELIB_ID, read without loading it.
static bool id_matches(const char *lib) {
    char path[1100], id[128] = {0};
    snprintf(path, sizeof path, "%s.id", lib);
    FILE *f = fopen(path, "rb");
    if (!f) return false;
    size_t n = fread(id, 1, sizeof id - 1, f);
    fclose(f);
    while (n && (id[n - 1] == '\n' || id[n - 1] == '\r')) id[--n] = 0;
    return !strcmp(id, GAMELIB_ID);
}

static bool exists(const char *p) {
    FILE *f = fopen(p, "rb");
    if (f) fclose(f);
    return f != NULL;
}

#ifdef __ANDROID__
// Keep generated executable code ONLY in the app's code_cache directory.
// The Java importer places a read-only ARM64 .so there, never in public storage.
// LARECOMP_DATA_ROOT is set to getFilesDir() by lasrecomp_android_start().
static bool android_private_game_path(char *out, size_t capacity) {
    const char *files = getenv("LARECOMP_DATA_ROOT");
    if (!files || files[0] != '/') return false;
    // Both files/ and code_cache/ are siblings in the package-private directory.
    int n = snprintf(out, capacity, "%s/../code_cache/%s", files, GAMELIB_ANDROID_NAME);
    if (n <= 0 || (size_t)n >= capacity) return false;
    struct stat st;
    return stat(out, &st) == 0 && S_ISREG(st.st_mode) &&
           st.st_size > 1024 && !(st.st_mode & 0222);
}
#endif

// The places to look, in order (gamelib.h). Returns how many were filled.
static int candidates(const char *game_dir, char out[3][1100]) {
    int n = 0;
    const char *env = getenv("LARECOMP_GAME_LIB");
    if (env && *env) snprintf(out[n++], 1100, "%s", env);
    char exe_side[1024];
    if (rt_resource(GAMELIB_NAME, NULL, exe_side, sizeof exe_side) && exists(exe_side))
        snprintf(out[n++], 1100, "%s", exe_side);
    if (game_dir) snprintf(out[n++], 1100, "%s/%s", game_dir, GAMELIB_NAME);
    return n;
}

bool gamelib_present(const char *game_dir) {
    if (g_tables) return true;
#ifdef __ANDROID__
    // Read-only app-owned code_cache was proven loadable on a real device.
    // Probe the private library first; preserve signed-APK fallback.
    char private_path[PATH_MAX];
    const char *path = android_private_game_path(private_path, sizeof private_path)
                       ? private_path : GAMELIB_ANDROID_NAME;
    void *lib = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!lib) return false;
    GameLibEntry entry = (GameLibEntry)(void *)dlsym(lib, GAMELIB_ENTRY);
    const GameLibTables *t = entry ? entry() : NULL;
    bool valid = t && t->abi == GAMELIB_ABI && t->id && !strcmp(t->id, GAMELIB_ID);
    dlclose(lib);
    return valid;
#else
    char c[3][1100];
    int n = candidates(game_dir, c);
    for (int i = 0; i < n; i++)
        if (exists(c[i]) && id_matches(c[i])) return true;
    return false;
#endif
}

static const GameLibTables *open_lib(const char *path) {
#ifdef _WIN32
    HMODULE h = LoadLibraryA(path);
    if (!h) { snprintf(g_error, sizeof g_error, "can't load %s (error %lu)", path, GetLastError()); return NULL; }
    GameLibEntry entry = (GameLibEntry)(void *)GetProcAddress(h, GAMELIB_ENTRY);
#else
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) { snprintf(g_error, sizeof g_error, "%s", dlerror()); return NULL; }
    GameLibEntry entry = (GameLibEntry)dlsym(h, GAMELIB_ENTRY);
#endif
    if (!entry) { snprintf(g_error, sizeof g_error, "%s: not game code", path); return NULL; }
    const GameLibTables *t = entry();
    if (!t || t->abi != GAMELIB_ABI || !t->id || strcmp(t->id, GAMELIB_ID)) {
        snprintf(g_error, sizeof g_error, "%s was built for another version", path);
        return NULL;  // (left loaded: nothing of it runs)
    }
#ifdef __ANDROID__
    // Inspect the module actually selected for gameplay, not a JNI import probe.
    const char *(*menu_tag)(void) = (const char *(*)(void))dlsym(h, "lasgame_mod_menu_v1");
    const char *(*fixed_tag)(void) = (const char *(*)(void))dlsym(h, "lasgame_mod_stable60_v2");
    rt_mod_begin(menu_tag ? menu_tag() : NULL, fixed_tag ? fixed_tag() : NULL);
#endif
    return t;
}

bool gamelib_load(const char *game_dir, char *why, size_t why_size) {
    static bool tried;
    if (!tried) {
        tried = true;
        snprintf(g_error, sizeof g_error, "the game code hasn't been built: set up the game files on the start screen");
#ifdef __ANDROID__
        char private_path[PATH_MAX];
        if (android_private_game_path(private_path, sizeof private_path)) {
            g_tables = open_lib(private_path);
            if (!g_tables) LOG("[gamelib] Android private code load failed: %s\n", g_error);
        } else {
            snprintf(g_error, sizeof g_error,
                     "Android: private liblasgame.so missing or writable in code_cache");
        }
        // Legacy signed-APK game module remains supported for private builds.
        if (!g_tables) {
            char prior_error[256];
            snprintf(prior_error, sizeof prior_error, "%s", g_error);
            g_tables = open_lib(GAMELIB_ANDROID_NAME);
            if (!g_tables && !strstr(g_error, "was built for another version"))
                snprintf(g_error, sizeof g_error, "%.235s", prior_error);
        }
#else
        char c[3][1100];
        int n = candidates(game_dir, c);
        const char *env = getenv("LARECOMP_GAME_LIB");
        for (int i = 0; i < n && !g_tables; i++) {
            if (!exists(c[i])) continue;
            bool given = i == 0 && env && *env;  // LARECOMP_GAME_LIB: loaded as given, the library's own id decides
            if (!given && !id_matches(c[i])) {
                snprintf(g_error, sizeof g_error, "%s was built for another version", c[i]);
                continue;
            }
            g_tables = open_lib(c[i]);
            if (g_tables) LOG("[gamelib] %s (%llu + %llu functions)\n", c[i], (unsigned long long)*g_tables->main_count,
                              (unsigned long long)*g_tables->sdk_count);
        }
#endif
    }
    if (!g_tables && why) snprintf(why, why_size, "%s", g_error);
    return g_tables != NULL;
}

const GameLibTables *gamelib_tables(void) { return g_tables; }
