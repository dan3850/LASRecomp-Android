/*
 * SDL's Android entry point for the eventual real LASRecomp game runtime.
 * This is an Android APK shared library, not a console/Termux executable.
 * Only call the original runtime when its native shared library is present.
 */
#include <SDL3/SDL.h>
#include <SDL3/SDL_system.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#ifdef __ANDROID__
#include <jni.h>
#include <SDL3/SDL_system.h>

static void boot_mark(const char *files, const char *stage, int value);

// SDL owns the Activity instance and Java VM. Keep the selected SAF URI
// available to native integrations without treating it as a POSIX path.
static void log_selected_game_tree(const char *files) {
    JNIEnv *env = (JNIEnv *)SDL_GetAndroidJNIEnv();
    jobject activity = (jobject)SDL_GetAndroidActivity();
    if (!env || !activity) return;
    jclass cls = (*env)->GetObjectClass(env, activity);
    if (!cls) { (*env)->DeleteLocalRef(env, activity); return; }
    jmethodID method = (*env)->GetMethodID(env, cls, "getExternalGameRoot",
                                           "()Ljava/lang/String;");
    if (method) {
        jstring uri = (jstring)(*env)->CallObjectMethod(env, activity, method);
        if (!(*env)->ExceptionCheck(env) && uri) {
            // URI is deliberately not logged: it may contain private names.
            boot_mark(files, "SAF folder supplied to native SDL bridge", 0);
            (*env)->DeleteLocalRef(env, uri);
        }
    }
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    (*env)->DeleteLocalRef(env, cls);
    (*env)->DeleteLocalRef(env, activity);
}
#endif

typedef int (*LASRecompStart)(const char *files_dir);

// This must work even if engine initialization aborts before platform log
// redirection. Keep a small append-only marker in the app's own files dir.
static void boot_mark(const char *files, const char *stage, int value) {
    if (!files || files[0] != '/') return;
    char path[2048];
    if (snprintf(path, sizeof path, "%s/lasrecomp_boot.txt", files) >= (int)sizeof path)
        return;
    FILE *f = fopen(path, "a");
    if (!f) return;
    fprintf(f, "[SDL] %s (%d)\n", stage, value);
    fclose(f);
}

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

    boot_mark(files, "SDL_main entered", 0);
#ifdef __ANDROID__
    log_selected_game_tree(files);
#endif
#ifdef __ANDROID__
    // Optional modest Android-only output gain, leaving stream timing untouched.
    if (!getenv("LARECOMP_AUDIO_GAIN")) setenv("LARECOMP_AUDIO_GAIN", "1.35", 0);
#endif

    /*
     * The full C/C++ runtime (with SDL3, Vulkan, FFmpeg and the generated
     * game code interface) is a separate build target. Don't pretend that
     * compiling runtime object files into CI produces a runnable library.
     */
    // The private recompiled game module resolves host HLE functions here.
// Keep the engine in the process-wide symbol group on Android.
    void *engine = dlopen("liblasrecomp_runtime.so", RTLD_NOW | RTLD_GLOBAL);
    if (!engine) {
        const char *reason = dlerror();
        boot_mark(files, "dlopen motor failed", 2);
        if (reason) boot_mark(files, reason, 2);
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "LASRecomp: native game runtime load failed: %s",
                     reason ? reason : "unknown error");
        return 2;
    }

    boot_mark(files, "motor loaded", 0);
    LASRecompStart start = (LASRecompStart)dlsym(engine, "lasrecomp_android_start");
    if (!start) {
        const char *reason = dlerror();
        boot_mark(files, "start symbol missing", 3);
        if (reason) boot_mark(files, reason, 3);
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "LASRecomp: game entry point missing: %s",
                     reason ? reason : "unknown error");
        dlclose(engine);
        return 3;
    }

    boot_mark(files, "entering engine", 0);
    int result = start(files);
    boot_mark(files, "engine returned", result);
    dlclose(engine);
    return result;
}
