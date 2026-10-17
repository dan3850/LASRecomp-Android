// Independent implementation inspired by Eden's LoadDiskResources: persist the
// recipe as well as the driver's opaque cache, then retain real prepared objects.
#include "replay.h"
#include "cache_identity.h"
#include <dirent.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#define REPLAY_VERSION 1u
#define REPLAY_LIMIT 4096u
#define REPLAY_BYTES (128u << 20)
#define REPLAY_WORDS (1u << 18)
#define REPLAY_MAGIC 0x5052414cu
typedef struct {
    uint32_t magic, version, endian, header_size;
    ReplayIdentity identity;
    uint32_t kind, state_size, words[2];
    uint64_t hash[2];
} DiskHeader;
typedef struct Entry {
    struct Entry *next;
    ReplayRecipe recipe;
    uint64_t hash[2];
    size_t bytes;
    uint8_t *data;
    void *object;
    bool building, attempted, dirty;
} Entry;
static struct {
    pthread_mutex_t lock;
    pthread_cond_t changed;
    pthread_t loader, writer;
    Entry *entries;
    ReplayIdentity identity;
    ReplayBuild build;
    ReplayDestroy destroy;
    void (*checkpoint)(void);
    char dir[160];
    bool enabled, stopping, loaded, loader_started, writer_started;
    unsigned count, active, waiting;
    size_t bytes;
    uint64_t registered, loaded_count, built, reused, failed, rejected, saved, waits, start_ns, load_ns;
} replay = {.lock = PTHREAD_MUTEX_INITIALIZER, .changed = PTHREAD_COND_INITIALIZER};

static uint64_t now_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + t.tv_nsec;
}
static void hash_bytes(uint64_t h[2], const void *data, size_t size) {
    const uint8_t *p = data;
    for (size_t i = 0; i < size; ++i) {
        h[0] = (h[0] ^ p[i]) * 0x100000001b3ull;
        h[1] = (h[1] ^ p[i]) * 0x9e3779b185ebca87ull;
        h[1] ^= h[1] >> 31;
    }
}
static bool valid_code(const uint32_t *p, uint32_t n, uint32_t model) {
    if (!p || n < 5 || n > REPLAY_WORDS || p[0] != 0x07230203 || !p[3] || p[3] > (1u << 20) || p[4]) return false;
    bool entry = false;
    for (uint32_t i = 5; i < n;) {
        uint32_t wc = p[i] >> 16, op = p[i] & 0xffff;
        if (!wc || wc > n - i) return false;
        if (op == 15 && wc >= 4 && p[i + 1] == model && p[i + 2] < p[3]) entry = true;
        i += wc;
    }
    return entry;
}
static size_t recipe_size(const ReplayRecipe *r) {
    if (!r->state || !r->state_size || r->state_size > REPLAY_STATE_MAX || (r->state_size & 3)) return 0;
    if (r->kind != REPLAY_GRAPHICS && r->kind != REPLAY_COMPUTE) return 0;
    if (!valid_code(r->code[0], r->words[0], r->kind == REPLAY_GRAPHICS ? 0 : 5)) return 0;
    if (r->kind == REPLAY_GRAPHICS) { if (!valid_code(r->code[1], r->words[1], 4)) return 0; }
    else if (r->words[1]) return 0;
    return r->state_size + ((size_t)r->words[0] + r->words[1]) * 4;
}
static void recipe_hash(const ReplayRecipe *r, uint64_t h[2]) {
    h[0] = 0xcbf29ce484222325ull; h[1] = 0x6a09e667f3bcc909ull;
    hash_bytes(h, &r->kind, sizeof r->kind); hash_bytes(h, &r->state_size, sizeof r->state_size);
    hash_bytes(h, r->words, sizeof r->words); hash_bytes(h, r->state, r->state_size);
    for (unsigned i = 0; i < 2; ++i) if (r->words[i]) hash_bytes(h, r->code[i], (size_t)r->words[i] * 4);
}
static bool equal(const Entry *e, const ReplayRecipe *r, const uint64_t h[2]) {
    if (memcmp(h, e->hash, sizeof e->hash) || r->kind != e->recipe.kind || r->state_size != e->recipe.state_size ||
        memcmp(r->words, e->recipe.words, sizeof r->words) || memcmp(r->state, e->recipe.state, r->state_size)) return false;
    for (unsigned i = 0; i < 2; ++i)
        if (r->words[i] && memcmp(r->code[i], e->recipe.code[i], (size_t)r->words[i] * 4)) return false;
    return true; // hashes select candidates; exact bytes decide reuse
}
static Entry *admit(const ReplayRecipe *r, const uint64_t h[2], size_t bytes, bool from_disk) {
    for (Entry *e = replay.entries; e; e = e->next) if (equal(e, r, h)) return e;
    if (replay.count == REPLAY_LIMIT || bytes > REPLAY_BYTES - replay.bytes) return NULL;
    Entry *e = calloc(1, sizeof *e);
    if (!e) return NULL;
    e->data = malloc(bytes);
    if (!e->data) { free(e); return NULL; }
    e->recipe = *r; e->bytes = bytes; memcpy(e->hash, h, sizeof e->hash);
    memcpy(e->data, r->state, r->state_size); e->recipe.state = e->data;
    size_t off = r->state_size;
    for (unsigned i = 0; i < 2; ++i) {
        e->recipe.code[i] = r->words[i] ? (uint32_t *)(e->data + off) : NULL;
        if (r->words[i]) memcpy(e->data + off, r->code[i], (size_t)r->words[i] * 4);
        off += (size_t)r->words[i] * 4;
    }
    e->next = replay.entries; replay.entries = e; replay.count++; replay.bytes += bytes;
    if (from_disk) replay.loaded_count++; else replay.registered++;
    return e;
}
static void finish(Entry *e, void *object, bool from_disk) {
    pthread_mutex_lock(&replay.lock);
    e->object = object; e->building = false; e->attempted = true;
    if (object) { if (from_disk) replay.built++; else e->dirty = true; }
    else replay.failed++;
    replay.active--; pthread_cond_broadcast(&replay.changed);
    pthread_mutex_unlock(&replay.lock);
}
static bool store_entry(const Entry *e) {
    char path[240], tmp[272];
    snprintf(path, sizeof path, "%s/%016llx%016llx.recipe", replay.dir,
        (unsigned long long)e->hash[0], (unsigned long long)e->hash[1]);
    snprintf(tmp, sizeof tmp, "%s.%ld.tmp", path, (long)getpid());
    DiskHeader h = {.magic = REPLAY_MAGIC, .version = REPLAY_VERSION, .endian = 0x01020304,
        .header_size = sizeof h, .identity = replay.identity, .kind = e->recipe.kind, .state_size = e->recipe.state_size,
        .words = {e->recipe.words[0], e->recipe.words[1]}, .hash = {e->hash[0], e->hash[1]}};
    FILE *f = fopen(tmp, "wb");
    if (!f) return false;
    bool ok = fwrite(&h, 1, sizeof h, f) == sizeof h && fwrite(e->data, 1, e->bytes, f) == e->bytes;
    if (fflush(f) || fsync(fileno(f))) ok = false;
    if (fclose(f)) ok = false;
    if (ok && rename(tmp, path) == 0) return true;
    remove(tmp); return false; // atomic replacement never removes a valid old file
}
static void *writer(void *unused) {
    (void)unused;
    for (;;) {
        pthread_mutex_lock(&replay.lock);
        Entry *pick = NULL;
        for (;;) {
            for (Entry *e = replay.entries; e; e = e->next) if (e->dirty) { pick = e; e->dirty = false; break; }
            if (pick || (replay.stopping && !replay.active)) break;
            pthread_cond_wait(&replay.changed, &replay.lock);
        }
        pthread_mutex_unlock(&replay.lock);
        if (!pick) break;
        bool ok = store_entry(pick);
        pthread_mutex_lock(&replay.lock);
        if (ok) replay.saved++;
        pthread_mutex_unlock(&replay.lock);
        if (!ok) fprintf(stderr, "[replay] recipe save failed: %s\n", strerror(errno));
        if (ok && replay.saved % 16 == 0 && replay.checkpoint) replay.checkpoint();
    }
    return NULL;
}
static void load_entry(const char *name) {
    char path[256]; snprintf(path, sizeof path, "%s/%s", replay.dir, name);
    FILE *f = fopen(path, "rb"); if (!f) return;
    DiskHeader h = {0}; uint8_t *data = NULL;
    bool ok = fread(&h, 1, sizeof h, f) == sizeof h && h.magic == REPLAY_MAGIC && h.version == REPLAY_VERSION &&
        h.endian == 0x01020304 && h.header_size == sizeof h && !memcmp(&h.identity, &replay.identity, sizeof h.identity) &&
        h.state_size && h.state_size <= REPLAY_STATE_MAX && !(h.state_size & 3) && h.words[0] <= REPLAY_WORDS && h.words[1] <= REPLAY_WORDS;
    size_t bytes = ok ? h.state_size + ((size_t)h.words[0] + h.words[1]) * 4 : 0;
    if (bytes) data = malloc(bytes);
    ok = ok && data && fread(data, 1, bytes, f) == bytes && fgetc(f) == EOF && !ferror(f);
    fclose(f);
    ReplayRecipe r = {.kind = h.kind, .state_size = h.state_size, .state = data,
        .words = {h.words[0], h.words[1]}};
    uint64_t hash[2] = {0};
    if (ok) {
        r.code[0] = (uint32_t *)(data + h.state_size); r.code[1] = r.code[0] + h.words[0];
        ok = recipe_size(&r) == bytes;
        if (ok) { recipe_hash(&r, hash); ok = !memcmp(hash, h.hash, sizeof hash); }
    }
    pthread_mutex_lock(&replay.lock);
    Entry *e = ok && !replay.stopping ? admit(&r, hash, bytes, true) : NULL;
    bool build = e && !e->building && !e->attempted;
    if (!ok) replay.rejected++;
    if (build) { e->building = true; replay.active++; }
    pthread_mutex_unlock(&replay.lock);
    free(data);
    if (build) finish(e, replay.build(&e->recipe, NULL), true);
}
static void *loader(void *unused) {
    (void)unused;
    setpriority(PRIO_PROCESS, 0, 10); // best effort: only this Linux/Android worker
    DIR *d = opendir(replay.dir);
    struct dirent *de;
    unsigned files = 0;
    while (d && (de = readdir(d)) && files < REPLAY_LIMIT) {
        size_t n = strlen(de->d_name);
        if (n != 39 || strcmp(de->d_name + 32, ".recipe")) continue;
        pthread_mutex_lock(&replay.lock); bool stop = replay.stopping; pthread_mutex_unlock(&replay.lock);
        if (stop) break;
        files++; load_entry(de->d_name);
    }
    if (d) closedir(d);
    if (replay.checkpoint) replay.checkpoint();
    pthread_mutex_lock(&replay.lock);
    replay.loaded = true; replay.load_ns = now_ns() - replay.start_ns;
    fprintf(stderr, "[replay] startup loaded=%llu rebuilt=%llu failed=%llu rejected=%llu time=%.1fms\n",
        (unsigned long long)replay.loaded_count, (unsigned long long)replay.built,
        (unsigned long long)replay.failed, (unsigned long long)replay.rejected, replay.load_ns / 1e6);
    pthread_cond_broadcast(&replay.changed); pthread_mutex_unlock(&replay.lock);
    return NULL;
}
void replay_start(const ReplayIdentity *identity, ReplayBuild build, ReplayDestroy destroy, void (*checkpoint)(void)) {
    replay.identity = *identity; replay.build = build; replay.destroy = destroy;
    replay.checkpoint = checkpoint;
    const char *e = getenv("LARECOMP_VK_STARTUP_REPLAY");
    replay.enabled = LAS_VK_CACHE_PERSISTENT && (!e || atoi(e) != 0);
    if (!replay.enabled) {
        replay.loaded = true;
        fprintf(stderr, "[replay] disabled (%s)\n", LAS_VK_CACHE_PERSISTENT ? "configuration" : "missing generated build identity");
        return;
    }
    uint64_t hash[2] = {0xcbf29ce484222325ull, 0x6a09e667f3bcc909ull};
    hash_bytes(hash, identity, sizeof *identity);
    hash_bytes(hash, LAS_VK_CACHE_BUILD_ID, sizeof(LAS_VK_CACHE_BUILD_ID));
    hash_bytes(hash, __VERSION__, sizeof(__VERSION__));
    mkdir("cache", 0755); mkdir("cache/startup-v1", 0755);
    snprintf(replay.dir, sizeof replay.dir, "cache/startup-v1/%016llx%016llx",
        (unsigned long long)hash[0], (unsigned long long)hash[1]);
    if (mkdir(replay.dir, 0755) && errno != EEXIST) {
        fprintf(stderr, "[replay] cache unavailable: %s; using normal compilation\n", strerror(errno));
        replay.enabled = false; replay.loaded = true; return;
    }
    replay.start_ns = now_ns();
    replay.writer_started = pthread_create(&replay.writer, NULL, writer, NULL) == 0;
    replay.loader_started = pthread_create(&replay.loader, NULL, loader, NULL) == 0;
    if (!replay.loader_started) replay.loaded = true;
    fprintf(stderr, "[replay] async startup path=%s writer=%d loader=%d\n", replay.dir, replay.writer_started, replay.loader_started);
}
void *replay_get(const ReplayRecipe *r, void *context) {
    size_t bytes = recipe_size(r);
    if (!bytes) return replay.build(r, context);
    uint64_t hash[2]; recipe_hash(r, hash);
    pthread_mutex_lock(&replay.lock);
    Entry *e = replay.enabled && !replay.stopping ? admit(r, hash, bytes, false) : NULL;
    if (!e) { pthread_mutex_unlock(&replay.lock); return replay.build(r, context); }
    uint64_t waited = 0;
    if (e->building) {
        waited = now_ns(); replay.waiting++; pthread_cond_broadcast(&replay.changed);
        while (e->building) pthread_cond_wait(&replay.changed, &replay.lock);
        replay.waiting--; replay.waits += now_ns() - waited;
    }
    if (e->object) { replay.reused++; void *object = e->object; pthread_mutex_unlock(&replay.lock); return object; }
    // A failed speculative build gets a normal demand retry with live inputs.
    e->building = true; replay.active++;
    pthread_mutex_unlock(&replay.lock);
    void *object = replay.build(&e->recipe, context);
    finish(e, object, false); return object;
}
void replay_stats(char *text, size_t capacity) {
    pthread_mutex_lock(&replay.lock);
    uint64_t elapsed = replay.loaded ? replay.load_ns : (replay.start_ns ? now_ns() - replay.start_ns : 0);
    snprintf(text, capacity, "replay registered=%llu loaded=%llu rebuilt=%llu reused=%llu saved=%llu failed=%llu rejected=%llu prepare=%.1fms wait=%.1fms loading=%d waiters=%u",
        (unsigned long long)replay.registered, (unsigned long long)replay.loaded_count, (unsigned long long)replay.built,
        (unsigned long long)replay.reused, (unsigned long long)replay.saved, (unsigned long long)replay.failed,
        (unsigned long long)replay.rejected, elapsed / 1e6, replay.waits / 1e6, !replay.loaded, replay.waiting);
    pthread_mutex_unlock(&replay.lock);
}
void replay_wait_startup(void) {
    pthread_mutex_lock(&replay.lock);
    while (!replay.loaded) pthread_cond_wait(&replay.changed, &replay.lock);
    pthread_mutex_unlock(&replay.lock);
}
void replay_stop(void) {
    pthread_mutex_lock(&replay.lock); replay.stopping = true; pthread_cond_broadcast(&replay.changed); pthread_mutex_unlock(&replay.lock);
    if (replay.loader_started) { pthread_join(replay.loader, NULL); replay.loader_started = false; }
    if (replay.writer_started) { pthread_join(replay.writer, NULL); replay.writer_started = false; }
    else for (Entry *e = replay.entries; e; e = e->next) if (e->dirty) store_entry(e);
}
void replay_destroy(void) {
    replay_stop();
    Entry *e = replay.entries;
    while (e) { Entry *next = e->next; if (e->object) replay.destroy(e->object); free(e->data); free(e); e = next; }
    replay.entries = NULL;
}
