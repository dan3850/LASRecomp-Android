// First-use GPU resources must be complete before recording dependent commands.
// States: 0 pending, 1 ready, 2 failed. Completion also wakes failed-build waits.
#pragma once
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>

static pthread_mutex_t vk_build_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t vk_build_cond = PTHREAD_COND_INITIALIZER;

static inline void vk_build_complete(_Atomic int *state, int result) {
    pthread_mutex_lock(&vk_build_lock);
    atomic_store(state, result);
    pthread_cond_broadcast(&vk_build_cond);
    pthread_mutex_unlock(&vk_build_lock);
}

static inline int vk_build_wait(_Atomic int *state) {
    int result = atomic_load(state);
    if (result) return result;
    pthread_mutex_lock(&vk_build_lock);
    while (!(result = atomic_load(state))) pthread_cond_wait(&vk_build_cond, &vk_build_lock);
    pthread_mutex_unlock(&vk_build_lock);
    return result;
}

static inline bool vk_build_ready(_Atomic int *state) {
#ifdef __ANDROID__
    // Dropping draws also drops depth/composite passes and one-shot compute
    // stores. Whole scenes can remain black while compilation catches up.
    return vk_build_wait(state) == 1;
#else
    return atomic_load(state) == 1;
#endif
}
