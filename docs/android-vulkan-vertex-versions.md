# Versioned Vulkan vertex/index snapshots

Branch: `android/eden-startup-pipeline-replay`.
Parent: `0d222722ee8e26b207bcd59aa4467ffe42304dd4`, preserving the user's
`1264249` GMEM update and `0d22272` Termux script. Both descend from `e165962`,
whose tree is identical to `16dfaa5`. No other branch was merged or copied.

## Implemented change

`guest_vertex_copy()` previously had one entry per address hash. A changed
range, or a colliding address, fell back to the transient ring while that entry
was referenced by an earlier draw. Repeated versions could not coexist.

The same 1024-entry table now has 256 buckets with four ways each. Each way
owns its buffer, CPU shadow and last-use timeline sequence. An identical version
can be reused across submissions, including while its previous GPU readers are
pending. Misses use a completed equal-sized allocation, an empty way, or the
oldest completed way, in that order. Recycling an equal-sized allocation also
works for a different guest address in the bucket, replacing all bytes and its
key. If all four ways are busy, the existing transient path remains available.

The change retains the 32 MiB mapped-buffer budget, 4 KiB minimum, 512 KiB
maximum, and the Android default enablement. CPU shadows require up to another
32 MiB, as before. `LARECOMP_VK_STATIC_VTX_CACHE=0` still disables this cache.
There is no change to shaders, pipelines, rendering quality, game timing or audio.

## Correctness conditions

- Every reuse compares all bytes requested by the draw against ordinary CPU
  shadow memory. A matching prefix does not validate a later changed tail.
- A buffer is updated, destroyed or repurposed only when its last-use sequence
  is at most the GPU's completed timeline value. Still-recording commands are
  protected by the pending sequence too. Cache misses never add a GPU wait.
- Full replacement writes both the shadow and mapped allocation, then calls
  `vmaFlushAllocation` before submission, including on non-coherent memory.
- Overflow, allocation failure and exhausted ways retain the existing fallback.
  Reset still clears snapshots only after the backend has made the GPU idle.

These rules follow Vulkan's
[host-write submission guarantees](https://docs.vulkan.org/spec/latest/chapters/synchronization.html#synchronization-submission-host-writes)
and VMA's [mapping and non-coherent allocation rules](https://gpuopen-librariesandsdks.github.io/VulkanMemoryAllocator/html/memory_mapping.html).

## Technical validation

- Compiled the complete `runtime/nvn/vulkan/exec.c` translation unit with Clang
  20.1.2, `-O2 -fPIC -Werror=implicit-function-declaration` on Linux x86-64.
- Ran `python3 tests/test_vulkan_gmem.py` using Vulkan 1.3 on Mesa Lavapipe,
  real VMA allocations, and no external-memory-host import or game files.
- Added a graphics test that records five colors from five versions of one
  guest vertex range. Four stay in distinct snapshots and the fifth uses the
  transient path. A host-signalled timeline gate deterministically holds the
  real GPU reads pending while guest bytes change. All five rendered pixels
  retain the expected colors after readback.
- In that synthetic test, 32 subsequent requests alternating among the four
  retained versions upload zero additional bytes. Pending readers stay intact;
  after completion a changed version refreshes an existing allocation.
- Checked full-byte/prefix-tail behavior, colliding addresses, the 32 MiB budget
  and idle cleanup. Existing GMEM LDG/STG, selective writeback, snapshot,
  compute-pool, counter-pair and R8 glyph-atlas tests also pass. Test shaders
  compile and pass `spirv-val`.
- `bash -n compilar-lasrecomp-eden-termux.sh` and `git diff --check` pass.

The test needs SDL3, Vulkan and VMA headers, a Vulkan loader/ICD, Clang,
`glslangValidator` and `spirv-val`. Set `VULKAN_TEST_CFLAGS`,
`VULKAN_TEST_LDFLAGS` and `VK_ICD_FILENAMES` for non-system installations.

## Expected benefit and device validation

The intended benefit is less transient copying and allocation churn when
geometry versions alternate or addresses collide. It is workload dependent:
checking up to four shadows adds CPU work, and four busy ways still fall back.
No RedMagic FPS improvement, Android APK build or device stability result is
claimed by the host checks above. Compile and test the same outdoor route and
indoor scene on the RedMagic 11 Pro, observing FPS, frame stalls and graphics.

The log now reports `vtx reused`, `refreshed` and `busy` per statistics interval.
`upload` now includes initial writes and refreshes of vertex snapshots, which
the previous counter omitted; raw upload totals from old builds are therefore
not directly comparable. The Termux wrapper preserves the private game library
and existing build caches, builds/signs locally, and copies a commit-named APK
to `/storage/emulated/0/Download/LASRecomp/`.
