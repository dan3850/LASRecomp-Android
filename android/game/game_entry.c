/*
 * SDL's Android entry point for the eventual real LASRecomp game runtime.
 * This is an Android APK shared library, not a console/Termux executable.
 * Only call the original runtime when its native shared library is present.
 */
#include <SDL3/SDL.h>
#include <SDL3/SDL_system.h>
#include "../../runtime/platform/android_documents.h"
#include <dlfcn.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#ifdef __ANDROID__
#include <jni.h>
#include <SDL3/SDL_system.h>

static void boot_mark(const char *files, const char *stage, int value);

static void document_exception(JNIEnv *env) {
    if (!(*env)->ExceptionCheck(env)) return;
    jthrowable error = (*env)->ExceptionOccurred(env);
    (*env)->ExceptionClear(env);
    int code = EIO;
    jclass security = (*env)->FindClass(env, "java/lang/SecurityException");
    jclass missing = (*env)->FindClass(env, "java/io/FileNotFoundException");
    if (security && (*env)->IsInstanceOf(env, error, security)) code = EACCES;
    else if (missing && (*env)->IsInstanceOf(env, error, missing)) code = ENOENT;
    jclass cls = (*env)->GetObjectClass(env, error);
    jmethodID text = cls ? (*env)->GetMethodID(env, cls, "toString", "()Ljava/lang/String;") : NULL;
    jstring message = text ? (jstring)(*env)->CallObjectMethod(env, error, text) : NULL;
    if (message && !(*env)->ExceptionCheck(env)) {
        const char *s = (*env)->GetStringUTFChars(env, message, NULL);
        if (s) {
            SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "SAF: %s", s);
            fprintf(stderr, "[fs] SAF: %s\n", s);
            (*env)->ReleaseStringUTFChars(env, message, s);
        }
    }
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    if (message) (*env)->DeleteLocalRef(env, message);
    if (cls) (*env)->DeleteLocalRef(env, cls);
    if (security) (*env)->DeleteLocalRef(env, security);
    if (missing) (*env)->DeleteLocalRef(env, missing);
    (*env)->DeleteLocalRef(env, error);
    errno = code;
}

// SDL owns the Activity instance and Java VM. Keep the selected SAF URI
// available to native integrations without treating it as a POSIX path.
// Native read-only SAF descriptor bridge. The Java method transfers fd
// ownership with ParcelFileDescriptor.detachFd(); caller must close(fd).
static int open_game_document_fd(const char *relative_path) {
    if (!relative_path || relative_path[0] == '/' || strchr(relative_path, '\\')) {
        errno = EINVAL; return -1;
    }
    JNIEnv *env = (JNIEnv *)SDL_GetAndroidJNIEnv();
    jobject activity = (jobject)SDL_GetAndroidActivity();
    if (!env || !activity) { errno = ENODEV; return -1; }
    int fd = -1;
    jclass cls = (*env)->GetObjectClass(env, activity);
    if (cls) {
        jmethodID method = (*env)->GetMethodID(env, cls, "openGameDocumentFd",
                                               "([B)I");
        if (method) {
            size_t length = strlen(relative_path);
            jbyteArray path = length <= INT_MAX ? (*env)->NewByteArray(env, (jsize)length) : NULL;
            if (path) {
                (*env)->SetByteArrayRegion(env, path, 0, (jsize)length, (const jbyte *)relative_path);
                jint result = (*env)->CallIntMethod(env, activity, method, path);
                if (!(*env)->ExceptionCheck(env)) fd = (int)result;
                (*env)->DeleteLocalRef(env, path);
            }
        }
        (*env)->DeleteLocalRef(env, cls);
    }
    document_exception(env);
    (*env)->DeleteLocalRef(env, activity);
    return fd;
}

__attribute__((visibility("default")))
int lasrecomp_android_open_document_fd(const char *relative_path) {
    return open_game_document_fd(relative_path);
}

// Only a small UTF-8 index crosses JNI. Native owns/frees the returned buffer.
__attribute__((visibility("default")))
int lasrecomp_android_romfs_manifest(char **out, size_t *length) {
    if (!out || !length) { errno = EINVAL; return -1; }
    *out = NULL; *length = 0;
    JNIEnv *env = (JNIEnv *)SDL_GetAndroidJNIEnv();
    jobject activity = (jobject)SDL_GetAndroidActivity();
    if (!env || !activity) { errno = ENODEV; return -1; }
    int result = -1;
    jclass cls = (*env)->GetObjectClass(env, activity);
    jmethodID method = cls ? (*env)->GetMethodID(env, cls, "getGameRomfsIndex", "()[B") : NULL;
    jbyteArray bytes = method ? (jbyteArray)(*env)->CallObjectMethod(env, activity, method) : NULL;
    if (!(*env)->ExceptionCheck(env) && bytes) {
        jsize n = (*env)->GetArrayLength(env, bytes);
        if (n > 0 && n <= (64 << 20)) {
            char *copy = malloc((size_t)n);
            if (copy) {
                (*env)->GetByteArrayRegion(env, bytes, 0, n, (jbyte *)copy);
                if (!(*env)->ExceptionCheck(env)) { *out = copy; *length = (size_t)n; result = 0; }
                else free(copy);
            } else errno = ENOMEM;
        } else errno = EINVAL;
    }
    document_exception(env);
    if (bytes) (*env)->DeleteLocalRef(env, bytes);
    if (cls) (*env)->DeleteLocalRef(env, cls);
    (*env)->DeleteLocalRef(env, activity);
    return result;
}

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
#ifdef __ANDROID__
    typedef void (*SetDocumentBridge)(LasOpenDocument, LasRomfsManifest);
    SetDocumentBridge set_documents = (SetDocumentBridge)dlsym(engine, "lasrecomp_android_set_document_bridge");
    if (!set_documents) {
        boot_mark(files, "engine missing SAF bridge registration", 4);
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "LASRecomp: incompatible engine; SAF bridge unavailable");
        dlclose(engine);
        return 4;
    }
    set_documents(lasrecomp_android_open_document_fd, lasrecomp_android_romfs_manifest);
    boot_mark(files, "SAF document callbacks registered in engine", 0);
#endif
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
