/* Test the actual guest-slot bridge used by future Android A64 stubs.
 * cc -std=c11 -Wall -Wextra -Werror -pthread tests/nxnative_guest_tls_test.c experimental/nxnative/android_guest_tls.c -o /tmp/nx_guest_tls && /tmp/nx_guest_tls
 */
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>

uintptr_t nx_android_guest_slot_get(unsigned slot);
int nx_android_guest_slot_set(unsigned slot, uintptr_t value);
void nx_android_guest_slot_reset(void);

static void *guest_thread(void *unused) {
    (void)unused;
    assert(nx_android_guest_slot_get(0) == 0);
    assert(nx_android_guest_slot_get(3) == 0);
    assert(nx_android_guest_slot_set(0, 0xCAFE) == 0);
    assert(nx_android_guest_slot_set(3, 0xBEEF) == 0);
    assert(nx_android_guest_slot_get(0) == 0xCAFE);
    nx_android_guest_slot_reset();
    assert(nx_android_guest_slot_get(0) == 0);
    return NULL;
}

int main(void) {
    nx_android_guest_slot_reset();
    assert(nx_android_guest_slot_set(0, 0x1234) == 0);
    assert(nx_android_guest_slot_set(1, 0x5678) == 0);
    assert(nx_android_guest_slot_set(2, 0x9ABC) == 0);
    assert(nx_android_guest_slot_set(3, 0xDEF0) == 0);
    assert(nx_android_guest_slot_set(4, 1) == -1);
    assert(nx_android_guest_slot_get(4) == 0);
    pthread_t thread;
    assert(pthread_create(&thread, NULL, guest_thread, NULL) == 0);
    assert(pthread_join(thread, NULL) == 0);
    assert(nx_android_guest_slot_get(0) == 0x1234);
    assert(nx_android_guest_slot_get(1) == 0x5678);
    assert(nx_android_guest_slot_get(2) == 0x9ABC);
    assert(nx_android_guest_slot_get(3) == 0xDEF0);
    nx_android_guest_slot_reset();
    assert(nx_android_guest_slot_get(0) == 0);
    puts("NX_GUEST_TLS_OK");
    return 0;
}
