// Real JNI/window-reference helper with a mocked VM and Android window owner.
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/android_window.h"

struct ANativeWindow { int id, refs; };
static struct ANativeWindow old_window = {1, 0}, new_window = {2, 0}, *current;
enum { OK, NO_ENV, NO_FRAME, NO_ACTIVITY, NO_CLASS, NO_METHOD, NO_SURFACE, THROW_SURFACE, NO_WINDOW, THROW_WINDOW };
static int failure, frames;
static bool exception;
static const jobject activity = (jobject)(uintptr_t)1, surface = (jobject)(uintptr_t)2;
static const jclass cls = (jclass)(uintptr_t)3;
static const jmethodID method = (jmethodID)(uintptr_t)4;

static jint push(JNIEnv *env, jint n) {
    (void)env; assert(n >= 3);
    if (failure == NO_FRAME) { exception = true; return -1; }
    ++frames; return 0;
}
static jobject pop(JNIEnv *env, jobject result) { (void)env; assert(frames == 1); --frames; return result; }
static jboolean check(JNIEnv *env) { (void)env; return exception; }
static void clear(JNIEnv *env) { (void)env; exception = false; }
static jclass object_class(JNIEnv *env, jobject obj) {
    (void)env; assert(frames == 1 && obj == activity);
    return failure == NO_CLASS ? NULL : cls;
}
static jmethodID static_method(JNIEnv *env, jclass c, const char *name, const char *signature) {
    (void)env; assert(c == cls && !strcmp(name,"getNativeSurface") && !strcmp(signature,"()Landroid/view/Surface;"));
    return failure == NO_METHOD ? NULL : method;
}
static jobject call(JNIEnv *env, jclass c, jmethodID m, ...) {
    (void)env; assert(c == cls && m == method);
    if (failure == THROW_SURFACE) { exception = true; return NULL; }
    return failure == NO_SURFACE ? NULL : surface;
}
static const struct JNINativeInterface_ jni = {.PushLocalFrame = push, .PopLocalFrame = pop,
    .ExceptionCheck = check, .ExceptionClear = clear, .GetObjectClass = object_class,
    .GetStaticMethodID = static_method, .CallStaticObjectMethod = call};
static JNIEnv env = &jni;
void *SDL_GetAndroidJNIEnv(void) { return failure == NO_ENV ? NULL : &env; }
void *SDL_GetAndroidActivity(void) { assert(frames == 1); return failure == NO_ACTIVITY ? NULL : activity; }
ANativeWindow *ANativeWindow_fromSurface(JNIEnv *e, jobject s) {
    assert(e == &env && s == surface);
    if (failure == NO_WINDOW || !current) return NULL;
    ++current->refs;
    if (failure == THROW_WINDOW) exception = true;
    return current;
}
void ANativeWindow_release(ANativeWindow *window) { assert(window && window->refs > 0); --window->refs; }

int main(void) {
    current = &old_window;
    ANativeWindow *held = vk_android_acquire_window();
    assert(held == &old_window && old_window.refs == 1 && !frames);
    // Java/SDL replaced the native window. The old held reference stays valid,
    // but the next acquisition must return the new window, without touching a
    // stale borrowed SDL property or acquiring an extra reference on it.
    current = &new_window;
    ANativeWindow *fresh = vk_android_acquire_window();
    assert(fresh == &new_window && new_window.refs == 1 && old_window.refs == 1 && !frames);
    ANativeWindow_release(held); ANativeWindow_release(fresh);
    assert(!old_window.refs && !new_window.refs);
    for (failure = NO_ENV; failure <= THROW_WINDOW; ++failure) {
        assert(!vk_android_acquire_window());
        assert(!frames && !exception && !old_window.refs && !new_window.refs);
    }
    failure = OK; current = NULL;
    assert(!vk_android_acquire_window() && !frames && !exception);
    puts("Android window: current Surface reference, replacement, missing Surface and JNI failures PASS (mocked VM)");
}
