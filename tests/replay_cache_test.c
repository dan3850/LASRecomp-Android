#include "../runtime/nvn/vulkan/replay.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sched.h>

// Catalog tests deliberately use a fake builder; the integration test uses
// validated, executable SPIR-V and the backend's real Vulkan builder instead.
static uint32_t vs[] = {0x07230203, 0x00010000, 0, 8, 0, 4u << 16 | 15, 0, 1, 0};
static uint32_t fs[] = {0x07230203, 0x00010000, 0, 8, 0, 4u << 16 | 15, 4, 1, 0};
static uint32_t cs[] = {0x07230203, 0x00010000, 0, 8, 0, 4u << 16 | 15, 5, 1, 0};
static uint32_t state[3] = {1, 2, 3};
static _Atomic unsigned calls;
static bool fail_speculative;
static bool gate_speculative, entered, release_gate;
static uint32_t gated_kind;
static pthread_mutex_t gate_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_changed = PTHREAD_COND_INITIALIZER;
static void *build(const ReplayRecipe *r, void *context) {
    assert(r->state_size == sizeof state);
    unsigned serial = atomic_fetch_add(&calls, 1) + 1;
    if (gate_speculative && !context) {
        pthread_mutex_lock(&gate_lock); gated_kind = r->kind; entered = true;
        pthread_cond_broadcast(&gate_changed);
        while (!release_gate) pthread_cond_wait(&gate_changed, &gate_lock);
        pthread_mutex_unlock(&gate_lock);
    }
    if (fail_speculative && !context) return NULL;
    unsigned *object = malloc(sizeof *object); assert(object); *object = serial;
    return object;
}
static ReplayRecipe graphics(void) {
    return (ReplayRecipe){.kind = REPLAY_GRAPHICS, .state_size = sizeof state, .state = state,
        .code = {vs, fs}, .words = {9, 9}};
}
static ReplayRecipe compute(void) {
    return (ReplayRecipe){.kind = REPLAY_COMPUTE, .state_size = sizeof state, .state = state,
        .code = {cs, NULL}, .words = {9, 0}};
}
static void *results[32];
static pthread_barrier_t barrier;
static void *request(void *p) {
    size_t id = (size_t)p; ReplayRecipe r = graphics();
    pthread_barrier_wait(&barrier);
    results[id] = replay_get(&r, (void *)1);
    return NULL;
}
static void *gated_request(void *recipe) { return replay_get(recipe, (void *)1); }
int main(int argc, char **argv) {
    assert(argc == 2);
    const char *mode = argv[1];
    ReplayIdentity identity = {.vendor = 1, .device = 2, .driver = 3, .api = 13, .features = 4, .state_abi = 12, .code = "catalog-test-v1"};
    if (!strcmp(mode, "driver")) identity.driver++;
    if (!strcmp(mode, "code")) strcpy(identity.code, "catalog-test-v2");
    if (!strcmp(mode, "gpu")) identity.device++;
    if (!strcmp(mode, "features")) identity.features++;
    if (!strcmp(mode, "uuid")) identity.uuid[0]++;
    if (!strcmp(mode, "failure")) fail_speculative = true;
    if (!strcmp(mode, "race")) gate_speculative = true;
    if (!strcmp(mode, "disabled")) setenv("LARECOMP_VK_STARTUP_REPLAY", "0", 1);
    replay_start(&identity, build, free, NULL);
    if (!strcmp(mode, "race")) {
        pthread_mutex_lock(&gate_lock);
        while (!entered) pthread_cond_wait(&gate_changed, &gate_lock);
        ReplayRecipe r = gated_kind == REPLAY_GRAPHICS ? graphics() : compute();
        pthread_mutex_unlock(&gate_lock);
        pthread_t demand; assert(!pthread_create(&demand, NULL, gated_request, &r));
        char stats[512]; bool waiting = false;
        for (unsigned i = 0; i < 1000000; ++i) {
            replay_stats(stats, sizeof stats);
            if (strstr(stats, "waiters=1")) { waiting = true; break; }
            sched_yield();
        }
        assert(waiting && calls == 1); // demand must not duplicate a pending startup build
        pthread_mutex_lock(&gate_lock); release_gate = true; pthread_cond_broadcast(&gate_changed); pthread_mutex_unlock(&gate_lock);
        void *object; pthread_join(demand, &object); assert(object);
        replay_wait_startup(); assert(calls == 2);
        assert(replay_get(&r, (void *)1) == object && calls == 2);
        replay_stop(); replay_destroy(); puts("replay startup/demand race PASS"); return 0;
    }
    replay_wait_startup();
    ReplayRecipe g = graphics(), c = compute();
    if (!strcmp(mode, "seed")) {
        pthread_t threads[32]; pthread_barrier_init(&barrier, NULL, 32);
        for (size_t i = 0; i < 32; ++i) assert(!pthread_create(&threads[i], NULL, request, (void *)i));
        for (unsigned i = 0; i < 32; ++i) pthread_join(threads[i], NULL);
        for (unsigned i = 0; i < 32; ++i) assert(results[i] && results[i] == results[0]);
        assert(calls == 1);
        assert(replay_get(&c, (void *)1)); assert(calls == 2);
    } else if (!strcmp(mode, "load")) {
        assert(calls == 2);
        void *a = replay_get(&g, (void *)1), *b = replay_get(&c, (void *)1);
        assert(a && b && a != b && calls == 2);
        // Different module bytes and state cannot alias a prepared object.
        state[0]++;
        void *changed = replay_get(&g, (void *)1); assert(changed && changed != a && calls == 3);
    } else if (!strcmp(mode, "failure")) {
        unsigned before = calls; assert(before == 2);
        assert(replay_get(&g, (void *)1) && replay_get(&c, (void *)1)); assert(calls == before + 2);
    } else if (!strcmp(mode, "corrupt")) {
        assert(calls <= 1);
        assert(replay_get(&g, (void *)1) && replay_get(&c, (void *)1)); assert(calls == 2);
    } else if (!strcmp(mode, "disabled") || !strcmp(mode, "unavailable")) {
        assert(!calls);
        free(replay_get(&g, (void *)1)); free(replay_get(&c, (void *)1)); assert(calls == 2);
    } else {
        assert(!calls); // incompatible namespace must not be loaded
        assert(replay_get(&g, (void *)1) && replay_get(&c, (void *)1)); assert(calls == 2);
    }
    replay_stop();
    char stats[512]; replay_stats(stats, sizeof stats); puts(stats);
    replay_destroy();
    printf("replay %s PASS\n", mode);
}
