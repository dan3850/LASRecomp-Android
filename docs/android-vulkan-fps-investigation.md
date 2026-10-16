# Android Vulkan FPS investigation (2026-10-16)

Base: `5f32058`, branch `android/external-game-folder`.

## Findings and changes

* Without external host-memory import, `portable_gmem_map` packs shader storage,
  uniform and shader-constant ranges into mapped buffers. Its existing cache
  expires at every submission. Thus unchanged inputs are copied again after
  every submit. This is a confirmed redundant-copy path, not proof that it
  accounts for all the reported overworld bandwidth or frame time.
* Read-only plans of 4 KiB–2 MiB now have a four-way persistent snapshot cache.
  Every packed range is compared byte for byte against a CPU shadow before
  cross-submission reuse. Changed inputs use an idle entry or fall back to the
  original transient path. Entries used by uncompleted or pending work cannot
  be overwritten. Writable compute dispatches never use this cache. Completed
  allocations of the same size are refreshed in place. Limits: 32 MiB mapped
  buffers plus up to 32 MiB CPU shadows. Reset releases them after GPU idle.
  `LARECOMP_VK_GMEM_SNAPSHOTS=0` restores the previous allocation path.
* Identical address-map uniform tables now share the existing per-submission
  constant deduplication path (separate graphics/compute slots).
* `upload` in the stats is allocated/copied mapped payload, including constants,
  vertex/index fallback, packed GMEM and texture staging. It is NOT a measurement
  of texture-only transfers or GPU transfer-engine bandwidth. Persistent snapshot
  writes are included; `gmem saved` reports bytes avoided by verified reuse.
* The timing diagnostic previously matched adjacent 16-byte records only inside
  one submission. It now retains the preceding raw GPU timestamp across
  submissions, resolves completed slots in queue order across ring wrap, and
  computes diagnostic intervals directly from raw GPU ticks. Host-offset
  recalibration no longer affects diagnostic differences. The adjacency heuristic
  remains: unrelated/nonadjacent records do not establish a frame pair, and
  reported intervals must not be equated with presentation FPS.

## Synchronization review and limits

The ring wait protects descriptor-pool/command-buffer reuse. Compute-to-CPU
snapshot waits protect shader results before CPU reads. Copy-to-CPU paths must
finish before exposing data to the game. The existing full barriers cover shared
images/buffers across passes, copies, dispatches and submissions. No fence or
barrier was removed without a resource-specific dependency proof. The supplied
900 ms wait total alone does not establish an unnecessary wait or distinguish
GPU execution, backlog and CPU/GPU dependency stalls.

No draws, effects, resolution, audio, input, game-speed logic, guest counter
values or presentation interval were changed. The GPU counter mode stays real.
These changes do not force 60 FPS. The exact cause of 20/30 FPS outdoors and the
fraction of the reported 460 MiB attributable to this path remain unproven
without a new device capture. Full comparisons cost CPU time; highly mutable
plans may benefit less. Do not run the forced-interval game-library experiment
when assessing normal game-speed behavior.

## Verification

`python3 tests/test_vulkan_gmem.py` executed against real Vulkan via Lavapipe,
without game files or host-memory import:

* Baseline: 61 submissions of unchanged 1 MiB inputs copied 61 MiB.
* Persistent cache: the same 61 submissions copied 1 MiB.
* Mutations preserve the in-flight old snapshot and produce new input data;
  completed allocations can refresh in place; writable compute is isolated.
* Ten timestamp submissions wrap the eight-slot ring; all nine adjacent-record
  intervals are recovered, including intervals split between submissions.
* Existing 13 translated compute LDG/STG cases, selective CPU writeback,
  same-submission invalidation, writable pool limits and same-frame R8 glyph
  atlas update pass. Synthetic GLSL passes SPIR-V validation.
* Termux update tests: 6 pass; dependency/incremental rebuild tests: 3 pass.
  `bash -n compilar-lasrecomp-termux.sh` and `git diff --check` pass.

This is a software Vulkan regression test, not Android/Adreno performance or a
visual comparison of Zelda. No APK was built or installed in this environment.
The existing Termux update/build/sign script remains unchanged:

```sh
bash "$HOME/LASRecomp-Android/compilar-lasrecomp-pasta-externa.sh"
```

It reuses existing compilation/dependency caches and writes the signed APK and
tracked-source ZIP under `/storage/emulated/0/Download/LASRecomp`. Keep the normal
private game library; importing a previously forced-interval library changes the
experiment independently of this renderer update.
