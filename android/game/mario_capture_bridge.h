// Keep an in-flight diagnostic callback alive until the engine can be unloaded.
#pragma once
#include <pthread.h>
typedef int (*MarioThreadCapture)(void);
static MarioThreadCapture mario_thread_capture;
static pthread_mutex_t mario_capture_bridge_lock=PTHREAD_MUTEX_INITIALIZER;
static void mario_capture_bridge_set(MarioThreadCapture callback) {
    pthread_mutex_lock(&mario_capture_bridge_lock);
    mario_thread_capture=callback;
    pthread_mutex_unlock(&mario_capture_bridge_lock);
}
static int mario_capture_bridge_run(void) {
    pthread_mutex_lock(&mario_capture_bridge_lock);
    int result=mario_thread_capture?mario_thread_capture():0;
    pthread_mutex_unlock(&mario_capture_bridge_lock);
    return result;
}
