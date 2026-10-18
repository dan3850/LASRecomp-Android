# PR #91 comparison: 4-way guest-copy reuse (experimental)

Base: `android/compare-pr91-worker-budget`. This is a new, independent Android upload optimization inspired by comparing memory-transfer bottlenecks with the Android PR #91 port; it does not copy the other port's renderer.

**Why:** The 2026-10-18 RedMagic 11 Pro Vulkan logs show roughly 280–294 MB of transient uploads per two seconds on the outdoor map, with high GPU wait times. Our `guest_copy` used a one-entry direct-mapped cache. Alternating guest addresses colliding in that cache led to needless copies even when the earlier immutable snapshot was still valid for this submission.

**Change:** Android defaults to four associative keys per address-hash bucket (still 4096 total entries). A larger snapshot may serve a smaller prefix. Each hit requires the *same submission and CPU-write generation* and identical guest address. Replacement only overwrites the cache **metadata**; it never overwrites the transient GPU data. Compute and inline-update invalidation remain unchanged. Other platforms keep the old direct-mapped policy. `LARECOMP_VK_GCOPY_4WAY=0` restores old Android behavior, `=1` enables it.

**Verify:** `python3 tests/test_vk_guest_copy.py` (run with `CC=clang` to use Clang). The renderer log now includes `guest-copy hit ... miss ... avoided ...MB` each interval. Compare identical outdoor routes with this option at 1 and 0, and compare total `upload` MB, `wait` ms and FPS. This does not claim improved FPS until verified on real hardware.

This change leaves shader translation, GMEM readback, synchronization, textures, shader pipeline replay, the private game library and the main Android branch untouched.
