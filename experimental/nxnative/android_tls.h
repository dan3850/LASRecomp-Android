/* Android/Linux replacement for nxnative's Apple pthread TSD slot reads.
 * This is a host-side prototype, not a drop-in replacement for rewritten A64
 * instructions: patch_nso.py must emit Android-compatible TLS access first.
 * MIT; original nxnative authors retain copyright in their own code.
 */
#ifndef NXNATIVE_ANDROID_TLS_H
#define NXNATIVE_ANDROID_TLS_H
#include <pthread.h>
#include <stdint.h>

enum nx_tls_slot { NX_TLS_X18, NX_TLS_TPIDR, NX_TLS_TPIDRRO, NX_TLS_GATE, NX_TLS_COUNT };
typedef struct { pthread_key_t keys[NX_TLS_COUNT]; unsigned created; } nx_tls_context;

static inline int nx_tls_init(nx_tls_context *ctx) {
    ctx->created = 0;
    for (unsigned i = 0; i < NX_TLS_COUNT; ++i) {
        if (pthread_key_create(&ctx->keys[i], NULL)) {
            while (ctx->created) pthread_key_delete(ctx->keys[--ctx->created]);
            return -1;
        }
        ctx->created++;
    }
    return 0;
}
static inline void nx_tls_destroy(nx_tls_context *ctx) {
    while (ctx->created) pthread_key_delete(ctx->keys[--ctx->created]);
}
static inline int nx_tls_set(nx_tls_context *ctx, enum nx_tls_slot slot, uintptr_t value) {
    if ((unsigned)slot >= ctx->created) return -1;
    return pthread_setspecific(ctx->keys[slot], (void *)value);
}
static inline uintptr_t nx_tls_get(const nx_tls_context *ctx, enum nx_tls_slot slot) {
    if ((unsigned)slot >= ctx->created) return 0;
    return (uintptr_t)pthread_getspecific(ctx->keys[slot]);
}
#endif
