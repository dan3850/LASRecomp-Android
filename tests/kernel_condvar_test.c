// Synthetic Horizon callers of the production kernel. No game code or data.
#include <assert.h>
#include <errno.h>
#include "kernel.c"

uint64_t plat_now_ns(void) {
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return (uint64_t)now.tv_sec * 1000000000ull + (uint64_t)now.tv_nsec;
}

static void current(KThread *t, uint32_t handle) {
    memset(t, 0, sizeof *t);
    t->handle = handle;
    t->prio = 44;
    assert(pthread_cond_init(&t->cond, NULL) == 0);
    t_cur = t;
}

static void timed_out(int64_t timeout) {
    KThread t;
    current(&t, 0x116);
    uint32_t mutex = t.handle, key = 0;
    uint32_t result = svc_wait_process_wide_key((uintptr_t)&mutex,
                                               (uintptr_t)&key, t.handle, timeout);
    assert(result == R_TIMEOUT);
    // Horizon leaves reacquisition after a timeout to the SDK. Acquiring here
    // means a normal non-recursive guest mutexLock would wait on itself.
    assert(mutex == 0);
    assert(g_waitlist == NULL && t.wait_kind == WAIT_NONE);
    assert(mutex_acquire_or_mark((uintptr_t)&mutex, t.handle));
    assert(mutex == t.handle);
    svc_arbitrate_unlock((uintptr_t)&mutex);
    assert(mutex == 0);
    pthread_cond_destroy(&t.cond);
}

static uint32_t shared_mutex, shared_key, waiter_result;
static KThread waiter;
static _Atomic bool waiter_returned;
static int64_t waiter_timeout;

static void *wait_thread(void *unused) {
    (void)unused;
    current(&waiter, 0x116);
    __atomic_store_n(&shared_mutex, waiter.handle, __ATOMIC_SEQ_CST);
    waiter_result = svc_wait_process_wide_key((uintptr_t)&shared_mutex,
                                             (uintptr_t)&shared_key,
                                             waiter.handle, waiter_timeout);
    atomic_store(&waiter_returned, true);
    return NULL;
}

static void wait_registered(void) {
    for (unsigned i = 0; i < 2000; i++) {
        pthread_mutex_lock(&g_klock);
        bool registered = g_waitlist == &waiter && waiter.wait_kind == WAIT_CONDVAR;
        pthread_mutex_unlock(&g_klock);
        if (registered) return;
        usleep(1000);
    }
    assert(!"condition waiter did not register");
}

static void signaled(bool contended) {
    KThread signaler;
    current(&signaler, 0x120);
    waiter_timeout = -1;
    pthread_t worker;
    assert(pthread_create(&worker, NULL, wait_thread, NULL) == 0);
    wait_registered();
    assert(shared_key == 1);
    if (contended) assert(mutex_acquire_or_mark((uintptr_t)&shared_mutex, signaler.handle));
    svc_signal_process_wide_key((uintptr_t)&shared_key, 1);
    assert(shared_key == 0);
    if (contended) {
        // A successful condvar signal must NOT bypass mutex ownership.
        pthread_mutex_lock(&g_klock);
        assert(waiter.wait_kind == WAIT_MUTEX);
        assert((shared_mutex & ~WAITERS_BIT) == signaler.handle);
        assert(!atomic_load(&waiter_returned));
        pthread_mutex_unlock(&g_klock);
        svc_arbitrate_unlock((uintptr_t)&shared_mutex);
    }
    assert(pthread_join(worker, NULL) == 0);
    assert(waiter_result == R_OK && shared_mutex == waiter.handle);
    assert(g_waitlist == NULL);
    pthread_cond_destroy(&waiter.cond);
    pthread_cond_destroy(&signaler.cond);
}

static void timeout_with_other_owner(bool signal_first) {
    KThread owner;
    current(&owner, 0x120);
    waiter_timeout = 500000000;  // real 500 ms timeout, not a clock substitution
    pthread_t worker;
    assert(pthread_create(&worker, NULL, wait_thread, NULL) == 0);
    wait_registered();
    assert(mutex_acquire_or_mark((uintptr_t)&shared_mutex, owner.handle));
    if (signal_first) svc_signal_process_wide_key((uintptr_t)&shared_key, 1);
    // The SVC must return on its deadline while the other owner still holds
    // the mutex. The guest SDK performs its own acquisition afterward.
    for (unsigned i = 0; i < 2000 && !atomic_load(&waiter_returned); i++) usleep(1000);
    assert(atomic_load(&waiter_returned));
    assert(pthread_join(worker, NULL) == 0);
    assert(waiter_result == R_TIMEOUT);
    assert((shared_mutex & ~WAITERS_BIT) == owner.handle);
    assert(g_waitlist == NULL);
    svc_arbitrate_unlock((uintptr_t)&shared_mutex);
    pthread_cond_destroy(&waiter.cond);
    pthread_cond_destroy(&owner.cond);
}

static void cancelled(void) {
    KThread t;
    current(&t, 0x116);
    uint32_t mutex = t.handle, key = 0;
    t.cancel = true;
    assert(svc_wait_process_wide_key((uintptr_t)&mutex, (uintptr_t)&key,
                                    t.handle, -1) == R_CANCELLED);
    assert(mutex == 0 && !t.cancel && g_waitlist == NULL);
    pthread_cond_destroy(&t.cond);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "zero")) timed_out(0);
    else if (!strcmp(argv[1], "finite")) timed_out(1000000);
    else if (!strcmp(argv[1], "signal")) signaled(false);
    else if (!strcmp(argv[1], "handoff")) signaled(true);
    else if (!strcmp(argv[1], "other-owner")) timeout_with_other_owner(false);
    else if (!strcmp(argv[1], "signal-before-timeout")) timeout_with_other_owner(true);
    else if (!strcmp(argv[1], "cancelled")) cancelled();
    else assert(!"unknown scenario");
    return 0;
}
