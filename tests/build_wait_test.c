#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <time.h>
#include "../runtime/nvn/vulkan/build_wait.h"

typedef struct { _Atomic int state, entered, done; int payload, seen; bool ready; } Build;
static void *consume(void *arg) {
    Build *b = arg;
    atomic_store(&b->entered, 1);
    b->ready = vk_build_ready(&b->state);
    if (b->ready) b->seen = b->payload;
    atomic_store(&b->done, 1);
    return NULL;
}
static void pause_briefly(void) { struct timespec t = {0, 20000000}; nanosleep(&t, NULL); }

int main(void) {
    Build a = {0}, b = {0};
#ifdef __ANDROID__
    pthread_t ta, tb;
    assert(!pthread_create(&ta,NULL,consume,&a));
    assert(!pthread_create(&tb,NULL,consume,&b));
    while (!atomic_load(&a.entered) || !atomic_load(&b.entered)) pause_briefly();
    pause_briefly();
    assert(!atomic_load(&a.done) && !atomic_load(&b.done)); // cannot discard either pending command
    b.payload = 0x1234;
    vk_build_complete(&b.state,1);
    assert(!pthread_join(tb,NULL));
    assert(b.ready && b.seen == 0x1234);
    pause_briefly();
    assert(!atomic_load(&a.done)); // another shader's broadcast is not this shader's completion
    vk_build_complete(&a.state,2);
    assert(!pthread_join(ta,NULL));
    assert(!a.ready && atomic_load(&a.done)); // compile errors must also wake and terminate
#else
    consume(&a);
    assert(atomic_load(&a.done) && !a.ready); // preserve desktop async policy
#endif
    for (int i = 0; i < 1000; ++i) {
        vk_build_complete(&a.state,1);
        assert(vk_build_ready(&a.state)); // completion before wait, including the synchronous build path
        vk_build_complete(&a.state,2);
        assert(!vk_build_ready(&a.state));
    }
    puts("Shader readiness: pending/success/failure, unrelated wakeups and completed builds PASS");
}
