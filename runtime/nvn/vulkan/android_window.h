// Acquire the current Java Surface, rather than retaining a borrowed SDL window
// property after surfaceDestroyed. Only used when rebuilding an Android surface.
#pragma once
#include <SDL3/SDL_system.h>
#include <android/native_window_jni.h>

static inline ANativeWindow *vk_android_acquire_window(void) {
    JNIEnv *env = (JNIEnv *)SDL_GetAndroidJNIEnv();
    if (!env) return NULL;
    if ((*env)->PushLocalFrame(env, 8) < 0) {
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
        return NULL;
    }
    ANativeWindow *window = NULL;
    jobject activity = (jobject)SDL_GetAndroidActivity();
    if (!activity || (*env)->ExceptionCheck(env)) goto done;
    jclass cls = (*env)->GetObjectClass(env, activity);
    if (!cls || (*env)->ExceptionCheck(env)) goto done;
    jmethodID get_surface = (*env)->GetStaticMethodID(env, cls, "getNativeSurface", "()Landroid/view/Surface;");
    if (!get_surface || (*env)->ExceptionCheck(env)) goto done;
    jobject surface = (*env)->CallStaticObjectMethod(env, cls, get_surface);
    if (!surface || (*env)->ExceptionCheck(env)) goto done;
    // fromSurface returns an acquired reference, even if SDL replaces/releases
    // its own native window concurrently. The caller must release this reference.
    window = ANativeWindow_fromSurface(env, surface);
done:
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionClear(env);
        if (window) ANativeWindow_release(window);
        window = NULL;
    }
    (*env)->PopLocalFrame(env, NULL);
    return window;
}
