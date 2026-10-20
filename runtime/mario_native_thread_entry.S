/*
 * Experimental ARM64 native guest-call boundary.
 *
 * uint64_t mario_native_call_leaf(uint64_t (*guest)(void *), void *arg,
 *                                  uint64_t guest_x18);
 *
 * x18 is reserved by the Android platform (including ShadowCallStack in
 * some builds). Keep the host x18 in stack memory throughout the guest call.
 * This function MUST NOT call any Android C code while guest x18 is active.
 *
 * Strict precondition: guest target is a trusted, AAPCS64-callable leaf that
 * returns normally, preserves callee-saved registers, and does NOT access
 * TPIDR_EL0/TPIDRRO_EL0, alter SP unexpectedly, perform SVC or invoke host
 * functions. No general Switch code or SDK entrypoint is safe under this
 * precondition. This is NOT a full native thread entry / SVC bridge.
 */
#if defined(__aarch64__)
.text
.p2align 2
.global mario_native_call_leaf
.type mario_native_call_leaf, %function
mario_native_call_leaf:
    // 48 bytes (16-byte aligned): x19/x20, x29/x30, host x18.
    stp x19, x20, [sp, #-48]!
    stp x29, x30, [sp, #16]
    str x18, [sp, #32]
    mov x19, x0
    mov x0, x1
    mov x18, x2
    blr x19
    // Restore the Android reserved register before touching any host C code.
    ldr x18, [sp, #32]
    ldp x29, x30, [sp, #16]
    ldp x19, x20, [sp], #48
    ret
.size mario_native_call_leaf, .-mario_native_call_leaf
#endif
