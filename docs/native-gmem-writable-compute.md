# Native GMEM writable compute — first implementation

Branch: android/native-pre-opengl, base 0d68e2a.

Previously, when VK_EXT_external_memory_host was unavailable, the
portable GMEM path bound a host-visible, CPU-mapped allocation as a writable
storage buffer. A shader could write that buffer repeatedly while the
Adreno was reading from slow host allocations. The host later invalidated
the same allocation and merged changed bytes into the guest heap.

The new path keeps the exact GMEM address table, plan bounds, guest-write
merge policy, and timeline completion logic. For writable COMPUTE maps
of at most 8 MiB, it uses a distinct device-preferred storage buffer and
a host-visible readback allocation per in-flight dispatch. The main
Vulkan command buffer first copies the packed guest ranges into the device
buffer and barriers transfer->compute, then dispatches, then barriers
compute->transfer, copies the result into the readback buffer, and
barriers transfer->host. No vkDeviceWaitIdle or per-dispatch wait was added.
The existing gmem_resolve_done invalidates ONLY after GPU completion, then
applies only differing bytes, preserving unrelated CPU writes.

Set LARECOMP_VK_GMEM_DEVICE_WRITES=0 to use the unchanged host-visible
fallback. Default is on for Android, off elsewhere. If allocation fails
or the packed range is >8 MiB, the host allocation is used. A/B
counters in renderer_stats: GMEM native cs, upload, readback, fallback.

Limit: this does not magically map arbitrary LDG/STG addresses outside the
guest's actually bound SSBO/UBO/driver-constant ranges; those retain the
existing defined fallback until a correct broader mapping is available.
This change is not a universal game-native renderer or a 60fps guarantee.

Validation: tests/vulkan_gmem_test.c now checks device-local buffer
selection and GPU->host readback on real compute shaders for the 12
independent subword/vector/invalid-address/UBO cases. Legacy behavior
is kept for the 13th intentionally adversarial two-writer case and for
read-only snapshot tests. Run tests/test_vulkan_gmem.py with a valid Vulkan
ICD and compiler; runtime testing on Adreno is still required.
