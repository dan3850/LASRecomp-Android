# Startup Pipeline Replay

Implemented independently on `android/eden-startup-pipeline-replay`, after
`05c8d647390915d5cc72d1a4e35644e338eba184`. The GMEM delta updates, versioned
vertex/index snapshots and restoration history remain intact.

## Design and reference

Eden's [`PipelineCache::LoadDiskResources()`](https://github.com/eden-emulator/mirror/blob/d8c6c59b679867d2595fdc0953df033475e23380/src/video_core/renderer_vulkan/vk_pipeline_cache.cpp)
loads saved descriptions and shader environments, queues graphics/compute
construction, and keeps the resulting objects in its runtime caches. Its opaque
Vulkan driver cache is a separate acceleration layer. This implementation adapts
those concepts to LASRecomp's C executor; no Eden implementation or reverted
LASRecomp patch was copied.

LASRecomp already cached GLSL-derived SPIR-V and opaque driver data. Neither
alone described which `VkPipeline` objects to recreate. The new replay catalog
records each successfully constructed guest graphics or compute pipeline as a
recipe containing its SPIR-V dependencies and static state. Graphics recipes
contain attachment/depth/stencil formats, samples, vertex formats/bindings,
strides/divisors, blend/write state, topology class and polygon mode. Compute
recipes contain the three local-size specialization constants. Dynamic states
remain set by the existing draw path. No guest pointer, `Prog *`, Vulkan handle,
texture or live descriptor is serialized.

At device startup, one background worker reads compatible recipes and recreates
modules, reflected descriptor layouts and real pipelines through the same raw
builders used by normal compilation. It retains the prepared pipelines and their
dependencies. A separate writer atomically saves successful new recipes during
play, without waiting for normal application exit. It checkpoints driver data
periodically; preparation completion and normal exit checkpoint it too.

Runtime translation still reconstructs current shader metadata from the game's
actual program. Current SPIR-V and static state are compared byte for byte with
catalog entries; hashes select candidates, never determine equality alone. A
match reuses the real prepared pipeline, with compatible live descriptor layouts.
Unknown recipes use normal compilation. Internal clear/present/post pipelines
retain their existing on-demand path and driver/SPIR-V caches.

## Synchronization and failure handling

- Only the render thread accesses the address-based program/draw tables. The
  startup worker uses independent, immutable descriptions and never guest RAM.
- The catalog mutex and condition variable admit one builder per exact recipe.
  A demand request arriving during its startup build waits for that entry,
  rather than duplicating it or using another pipeline. Other recipes can build
  concurrently. Shader compiler instances remain thread-local.
- Program/pipeline readiness uses an atomic state plus condition notification.
  Required draws and dispatches wait for their resource instead of being
  omitted while compilation is pending. A genuine normal compilation failure
  reports an explicit fatal error rather than silently drawing incomplete output.
- A speculative creation failure can be retried using the normal live context.
  Speculative module/layout creation failures do not terminate the game.
- Prepared objects remain valid across guest resets because their keys and
  dependencies contain no guest addresses. Background work stops before the exit
  GPU wait. Explicit catalog destruction requires stopped demand callers and GPU
  idle; the application normally retains the objects until process teardown.
- The Vulkan pipeline cache uses default internal synchronization. Snapshot
  writers have their own mutex and retry `VK_INCOMPLETE`; writes rename over the
  old file atomically, without deleting a valid previous cache first.

## Compatibility and persistence

`tools/vulkan-cache-build-id.py` generates a SHA-256 identity from renderer,
translator and relevant interface sources and build recipes. Unchanged content
does not touch the generated header's mtime. Termux and Android renderer build
entry points generate it automatically, and compiler depfiles rebuild affected
objects when it changes. Unidentified custom builds use normal compilation and
disable persistent replay/SPIR-V reuse until that header is generated/included.

The namespace also includes compiler identity, cache format version, state ABI,
GPU vendor/device, driver/API versions, enabled relevant features/options and
`pipelineCacheUUID`. Rebuilds of identical sources do not invalidate it merely
because the build time changed. Old namespaces remain on disk.

Recipes are under `cache/startup-v1/<identity>/`. Headers, lengths, checksums,
SPIR-V instruction bounds and execution models are checked before admission.
Static state and formats are checked before speculative driver calls. Truncated,
incompatible or damaged files fall back to normal construction. The in-memory
catalog admits up to 4096 entries and 128 MiB of recipe payload; overflow retains
normal compilation. Files include dependencies, so shader data may be repeated
between different pipeline states. These are private runtime caches, not assets
to commit or distribute.

The SPIR-V cache now includes source/compiler/options identity and a checked
header/checksum, with thread-safe directory setup and atomic per-process writes.
Legacy cache files are preserved. Opaque Vulkan data is size bounded and its
vendor/device/UUID header is verified before loading.

## Diagnostics

`[replay] async startup` identifies the namespace and active workers. Startup
completion and renderer statistics report `registered`, `loaded`, `rebuilt`,
`reused`, `saved`, `failed`, `rejected`, `prepare`, `wait`, `loading` and `waiters`.
`reused` counts pipeline requests satisfied from retained catalog objects, not
every draw through the executor's existing in-memory table. `wait` measures
requests waiting for the same catalog entry; it is separate from GPU waits.
SPIR-V diagnostics report `hits` and successful `compiled` counts.
`LARECOMP_VK_STARTUP_REPLAY=0` in the native process environment disables replay.

## Validation

- Compiled changed executor/device/shader/catalog units with Clang 20.1.2,
  `-O2 -fPIC -Werror=implicit-function-declaration` on Linux x86-64.
- Catalog tests across fresh processes cover 32 concurrent requests, a gated
  startup/demand race, speculative failure and normal retry, GPU/driver/UUID/
  code/feature invalidation, truncation/version/checksum/oversized records,
  unavailable storage, disabled replay and atomic-write cleanup. AddressSanitizer
  and UndefinedBehaviorSanitizer pass. LeakSanitizer is disabled because this
  execution environment cannot inspect process tasks; it is not a leak check.
- Real Vulkan 1.3 tests on Mesa Lavapipe, with shaderc, VMA and Khronos validation,
  pass without Vulkan validation errors. A cold process registers two graphics
  states and one specialized compute pipeline. A second process rebuilds and
  reuses all three, with zero demand pipeline builds and three SPIR-V disk hits.
  The rendered tinted pixel and compute result match. A third process with a
  damaged SPIR-V file recompiles that shader and still reuses the prepared
  pipelines correctly. Normal asynchronous worker/readiness paths are exercised.
- Existing GMEM LDG/STG, selective writeback, snapshot/pool, timing diagnostic,
  R8 atlas and versioned vertex/index tests pass. Synthetic emitted SPIR-V passes
  `spirv-val`. Shell syntax and `git diff --check` pass.

Run the catalog tests with `python3 tests/test_pipeline_replay.py`. Enable the
extended Vulkan tests with `VULKAN_TEST_REAL_SHADERS=1 python3
tests/test_vulkan_gmem.py`, providing SDL3, Vulkan, VMA and shaderc include/library
paths through `VULKAN_TEST_CFLAGS` / `VULKAN_TEST_LDFLAGS`, and the usual Vulkan
ICD/layer environment variables. Native device compilation needs compatible
desktop SDL3 headers; the Android screenshot path remains unchanged.

No Android APK, RedMagic stability result or FPS gain is claimed by these host
checks. Test one visit to the target areas, close/reopen the game and revisit the
same route. Check reconstruction/reuse and SPIR-V counters as well as frame stalls
and graphics. Newly encountered state still requires real compilation, so replay
cannot eliminate every first-use pause. The Termux build reuses existing
dependencies and private game code; it does not clean their caches.
