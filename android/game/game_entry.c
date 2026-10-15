/*
 * SDL's Android entry point for the eventual real LASRecomp game runtime.
 * This is an Android APK shared library, not a console/Termux executable.
 * Only call the original runtime when its native shared library is present.
 */
#include <SDL3/SDL.h>
#include <SDL3/SDL_system.h>
#include <dlfcn.h>
#include <stdlib.h>

typedef int (*LASRecompStart)(const char *files_dir);

__attribute__((visibility("default")))
int SDL_main(int argc, char **argv) {
    (void)argc;
    (void)argv;

    const char *files = SDL_GetAndroidInternalStoragePath();
    if (!files || files[0] != '/') {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "LASRecomp: Android private files directory is unavailable");
        return 1;
    }

    /*
     * The full C/C++ runtime (with SDL3, Vulkan, FFmpeg and the generated
     * game code interface) is a separate build target. Don't pretend that
     * compiling runtime object files into CI produces a runnable library.
     */
    void *engine = dlopen("liblasrecomp_runtime.so", RTLD_NOW | RTLD_LOCAL);
    if (!engine) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "LASRecomp: native game runtime not packaged: %s", dlerror());
        return 2;
    }

    LASRecompStart start = (LASRecompStart)dlsym(engine, "lasrecomp_android_start");
    if (!start) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "LASRecomp: game entry point missing: %s", dlerror());
        dlclose(engine);
        return 3;
    }

    int result = start(files);
    dlclose(engine);
    return result;
}
