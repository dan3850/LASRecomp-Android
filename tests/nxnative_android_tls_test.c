/* Regression test for experimental/nxnative/android_tls.h.
 * Run from repository root:
 * cc -std=c11 -Wall -Wextra -Werror -pthread -Iexperimental/nxnative tests/nxnative_android_tls_test.c -o /tmp/nx_tls_test && /tmp/nx_tls_test
 */
#include "android_tls.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>

static nx_tls_context context;

static void *worker(void *unused) {
    (void)unused;
    assert(nx_tls_get(&context, NX_TLS_X18) == 0);
    assert(nx_tls_set(&context, NX_TLS_X18, 0xBEEF) == 0);
    assert(nx_tls_get(&context, NX_TLS_X18) == 0xBEEF);
    assert(nx_tls_get(&context, NX_TLS_GATE) == 0);
    return NULL;
}

int main(void) {
    assert(nx_tls_init(&context) == 0);
    assert(nx_tls_set(&context, NX_TLS_X18, 0xCAFE) == 0);
    assert(nx_tls_set(&context, NX_TLS_GATE, 0x1234) == 0);
    pthread_t thread;
    assert(pthread_create(&thread, NULL, worker, NULL) == 0);
    assert(pthread_join(thread, NULL) == 0);
    assert(nx_tls_get(&context, NX_TLS_X18) == 0xCAFE);
    assert(nx_tls_get(&context, NX_TLS_GATE) == 0x1234);
    assert(nx_tls_set(&context, NX_TLS_TPIDRRO, 0x4321) == 0);
    assert(nx_tls_get(&context, NX_TLS_TPIDRRO) == 0x4321);
    nx_tls_destroy(&context);
    puts("NX_TLS_OK");
    return 0;
}
