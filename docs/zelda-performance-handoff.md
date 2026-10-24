# Zelda Android performance: continuation checkpoint

Updated: 2026-10-24. Read this before continuing the experimental Zelda work.
The user requested that every delivery list what remains and leave a durable
checkpoint for another assistant if the conversation or credits end.

## Target and rules

- Repository: `dan3850/LASRecomp-Android`.
- Working branch: `experimental/zelda-links-awakening-ryujinx-nativeaot`.
- Game: Link's Awakening 1.1.0, title `01006BB00C6F0000`, supplied build ID
  `909E904AF78AC1B8DEEFE97AB2CCDB51968F0EC7`.
- Device: RedMagic 11 Pro, Snapdragon 8 Gen 5, Adreno 840; Android ARM64 Vulkan.
- Keep the working ScarletNX runtime and the Stable60 toggle/AOT. No stable
  branch changes, `git clean`, cache deletion or unnecessary full AOT rebuild.
- The user compiles in Termux. Do source/component verification on the host;
  do not spend time trying to build a whole Android/game image here.
- No skipped required draws, incomplete shaders or weakened synchronization.
- Publish changes to GitHub; provide exact Termux commands. Preserve a usable
  reference APK and prefer independent ON/OFF comparisons in one new APK.

## Last known good reference

**`d2121261bb83ed2edcbde0882431d1d2ce7bee0d`** is now the latest
user-approved performance reference. After its uniform-snapshot delivery the
user said: "Melhorou o caminho é continuar trazendo melhorias de lá" and
authorized continuing nxnative adaptations. The earlier transfer revision
`9b405a615cfcad9c8c0720675ed4c0f9c3b68d63` also received substantial positive
feedback and remains a preserved reference. Both reports are qualitative;
exact toggle states and controlled OFF/ON telemetry have not been provided.
Do not invent percentages or declare stable 60 FPS.

Build the latest reference with
`SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-uniformes-termux.sh`.
Output: `Download/ZeldaRecomp/Zelda-SNX-UNIFORMES.apk`.
Preserve that APK and `Zelda-SNX-NXNATIVE-TRANSFER.apk`. Keep transfer reuse
and uniforms ON, capture OFF, telemetry LEVE, the native translator and the
same Stable60 state when comparing the next independent option. If rebuilding
the uniform profile from newer code, explicitly keep the clear option OFF
for the reference trial; a saved ON preference overrides the profile default.

## Implemented and published

| Revision | Delivered behavior | Evidence and limits |
|---|---|---|
| `464c688` | Bounded CPU/Vulkan/frame telemetry and log analyzer. | Renderer, guest queue and successful presentation enqueue are distinct streams. Neither actual scan-out nor simulation FPS is measured. |
| `5a8698c` | Optional confirmed-completion waits and isolated Ryujinx persistence. | Runtime options; do not confuse this with Android write tracking. |
| `9f9ea9a`, `1f4d2a7` | Termux test portability fixes, including `/dev/full` and the Bionic `O_SYNC` macro conflict. | Do not remove these fixes or weaken tests to make a build pass. |
| `02f1f3c`, `3b02e52` | Bounded graphics evidence and shader capture that bypasses prewarm when requested. | Performance trials must have capture OFF; detailed GPU logging adds overhead. |
| `72ccaec`, `6ed5cef` | Operand-exact FSWZADD experiment, then default OFF after negative phone feedback. | The user saw no visual fix and possible slowdown. Keep `SCARLETNX_ZELDA_FSWZADD=0`; preserve the separate experiment cache. |
| `24250a6` | Optional range-qualified CPU reads for texture hashing. | All bytes still hashed; page-rounded GPU ownership and visibility checks preserved. Not a dirty-page tracker. |
| `9b405a6` | Fence-retired transfer-buffer pool, contiguous row coalescing and eligible full linear DMA overwrites without old-destination staging. | New generation on every reused resource; bounded pool. Previous delivery reported 21 host tests passing. User subsequently reported a large improvement. |
| `d212126` | Optional graphics-only immutable uniform snapshots, reuse after strict content checks within the same submission, and bypass of promotion copies. | 25 host tests pass; full patched `buffer.c`, `render.c`, `renderer.c` pass C syntax checks. User subsequently reported improvement; controlled device metrics remain pending. |
| `clear-load-v1` delivery (locate with `git log -1 -- tools/patch_scarletnx_zelda_clear_load.py`) | Optional eligible full clears as new-pass load actions, preserving same-pass reuse and conservative fallbacks. | 29 host tests pass; 40 old/new pixel-model scenes and full patched C syntax checks. Not yet tested on the Android Vulkan driver; no FPS gain claimed. |

## Current stopping point: clear-load adaptation delivered; device A/B pending

The first uniform adaptation is implemented, host-validated and now positively
reviewed by the user. The next adaptation is implemented in
`tools/patch_scarletnx_zelda_clear_load.py` and `tools/zelda-perf/clear_load.h`.
The user explicitly asked to resume from the exact stopping point without
redoing existing work. Do not rewrite the transfer/uniform implementations
or restart the nxnative audit. Read [the clear scope](zelda-clear-load.md)
and check whether device logs/feedback for this delivery have arrived first.

- Option: `SNX_VK_CLEAR_LOAD=1`, **Limpezas completas no inicio do passe**.
  Default ON only in the new clear profile (saved preference respected);
  runtime/ordinary audit default OFF. Roll back this step alone by switching
  it OFF and restarting the game process. Keep approved transfers/uniforms ON.
- Only immediate, unpredicated full clears of single-layer, equal-extent,
  distinct bound images qualify, when the original rules already need a new
  pass. Full color masks and complete actual depth/stencil aspects are
  required. Open-pass clears, scissors, partial masks/aspects, arrays, volumes,
  aliases and invalid selections retain the original commands. There is no
  cross-command lazy clear, new pass break, discard or removed barrier.
- Existing store operations, color bits, chosen views, depth clamping,
  stencil truncation, feedback and all write/full/undefined bookkeeping stay.
  Actual delayed recorder functions are exercised, including stack-value
  lifetime. Full stack apply/revert restores every source byte.
- `SNX_CLEAR_LOAD_META_V1` and `SNX_CLEAR_LOAD_V1` count requests, candidates,
  folded commands, same-pass fallbacks, per-aspect clears and initialized
  pixel areas. Areas are not measured bandwidth savings; use matching complete
  windows in the analyzer. Forty old/new scenes keep pixel-model contents,
  metadata, pass/query/profiler/barrier and masked-clear work equivalent.
- `compilar-zelda-clears-termux.sh` validates the signed APK's current profile
  assets and compiled markers, then produces `Zelda-SNX-CLEARS.apk`. It
  preserves the approved uniform/transfer APK filenames and takes a once-only
  before-clears backup of an existing uniform APK. Reuse the existing AOT,
  Gradle, CMake, Ninja and shader caches. FSWZADD stays OFF.
- All 29 host audit tests pass with zero skips and a real `spirv-val`.
  Complete patched `render.c`, `renderer.c`, `record.c`, shell syntax and
  whitespace checks pass. No Java/Android APK or game run was performed here.
  A pixel model does not establish Vulkan-driver correctness or an FPS gain.

**Resume:** first inspect OFF/ON phone evidence for this clear option, with
transfers/uniforms ON and capture OFF. Check `folded_commands`, frame p95/p99
and visuals; maintain the last approved `d212126` reference until validated.
If no device evidence is available, the next useful independent task is
read-only diagnosis and bounded instrumentation of Android write-watch
availability/cost, using the existing tracker before adding any fallback.
Do not transplant fault handlers or shared pools without the alias/ownership
proofs listed below. Broader partial/deferred clears and load/store elimination
remain separate, unimplemented work.

## Approved uniform scope and existing mechanisms (preserve)

- `maxwell3d.c:r3d_const_upload/r3d_const_flush` already batches inline constant
  words and writes them through `gmem_write`. Do not implement batching again.
- `render.c:cb_get` already caches per-stage bindings and uses strict buffer
  reads. `stage_set` already limits copies to `ShaderInfo.cbuf_max`.
- `buffer.c:buf_get` promotes content stable on two checks through `make_own`.
  `make_own` allocates device storage, stages bytes, ends the render pass,
  copies and inserts a barrier. Strict constant reads use this path too.
- `tools/patch_scarletnx_zelda_uniform.py` now adds graphics-only
  `vk_buf_get_uniform`, leaving normal vertex and strict compute reads on
  their old policy. Graphics uniforms <=64 KiB keep strict checks and pending
  GPU-result handling but use existing immutable staging rather than promote
  through a copy that ends rendering. An identical staging snapshot can be
  reused only in its original submission, rechecked after guest reads.
- This is not the complete nxnative deferred-uniform-write machinery. Inline
  writes remain immediately guest-visible through the original APIs. Complete
  deferred GPU updates and partial shadows are still potential later work.
- Runtime option: `SNX_VK_UNIFORM_STREAM=1`; UI:
  `Uniformes em snapshots reutilizaveis`. Defaults ON in the uniform and clear
  profiles, OFF in the ordinary audit/transfer variant unless the user has
  explicitly saved a preference. Transfer reuse remains enabled in the new
  variant; FSWZADD stays OFF. Every trial uses a fresh game process.
- `compilar-zelda-uniformes-termux.sh` produces
  `Download/ZeldaRecomp/Zelda-SNX-UNIFORMES.apk`, validates current assets and
  runtime markers, and does not overwrite `Zelda-SNX-NXNATIVE-TRANSFER.apk`.
  It saves an additional before-uniforms backup when the reference exists.
- `SNX_UNIFORM_META_V1` and `SNX_UNIFORM_V1` report strict mode, requests,
  reused snapshots/bytes, promotion bypass decisions and staging bytes.
  The analyzer requires complete matching windows. A bypass decision is not
  a measurement of successful counterfactual allocations or milliseconds.
- Actual-source fixtures preserve old draws' bytes across updates, check full
  hashes, epochs/submissions (including a submit during a guest read), pending
  graphics/composed/compute results, shared vertex/UBO cache entries, strict
  compute policy, noncontiguous reads, temporary/staging/allocation failure,
  oversized/zero ranges, OFF/invalid options, signed asset gates and rollback.
- In a controlled five-check 16-byte to 64-KiB uniform case, the old path has
  one dedicated-buffer copy/pass end; the new path has none and reuses the
  staging snapshot. Both hash all bytes on all five required checks. This
  establishes work removed in that case, not a phone FPS gain.

The immediate clear adaptation described above completes that former stopping
point. Do not implement it a second time. The uniform scope remains in
[`zelda-uniform-snapshots.md`](zelda-uniform-snapshots.md).

## Remaining work inventory

These are adaptation candidates, not a claim that every one will improve this
Zelda. The existing mechanisms must be preserved and extended, not recreated.

| Front | Status / next task |
|---|---|
| Graphics uniform snapshots and small updates | First adaptation delivered and positively reviewed on device; controlled metrics pending. Full deferred GPU updates/partial uniform shadows remain separate work. |
| Android dirty-page tracking | Not active in supplied device logs. ScarletNX already implements generation tables and async userfaultfd/PAGEMAP_SCAN. Diagnose support/permissions; a fault fallback needs CPU aliases, host writes and GPU ownership traps. |
| Broader persistent/shared GPU pools | Only transfer-result pooling adapted. A whole-pool shared-memory path needs Vulkan/driver support, alias and lifetime proofs. |
| Binding/state fast paths | Descriptor reuse already exists; evaluate skipping repeated reconstruction through validated generations. |
| Texture upload batches / dynamic image versions | Existing staging, image reuse and GPU conversion are present. Profile remaining transitions and dependencies before extending them. |
| Fold clears into render-pass load actions | First immediate new-pass full-clear adaptation delivered; Android A/B pending. Partial, layered and deferred-clear extensions remain unimplemented. |
| Attachment load/store elimination | Experimental. Needs complete reads/writes/alias/bindless tracking and CPU observers. |
| Pass merging / tile-local feedback | Experimental; nxnative itself defaults its broad TBDR optimization set OFF because bindless defeats its dependency inference. Do not enable it blindly. |
| More precise Vulkan barriers | Candidate; preserve producer/consumer visibility and required waits. |
| Submission segmentation | Recording is already asynchronous. Compare submit granularity against GPU idle time; extra submits may hurt. |
| Full offline shader preparation | Native persistence/prewarm already exists; broader Zelda extraction, variants and resource facts remain. |
| Pipeline lookahead prediction | Existing workers overlap compilation with decode; evaluate any additional benefit from nxnative's ahead-of-use prediction. |
| Full Ryujinx resource/stage bridge | Both inspected live adapters remain fragment-oriented; SSBO/storage-image support and vertex/compute integration still missing. Native ScarletNX already translates these stages, so this alone does not explain missing effects. |
| CPU spin/yield policy | Candidate; integrate with ScarletNX's emulated core scheduler. nxnative's host-thread sleeps cannot be transplanted blindly. |
| Frame pacing / physical display evidence | Existing pacing and FIFO presentation remain; actual scan-out feedback is not supplied by current FPS logs. |
| Per-pass pixel capture and bandwidth/dependency analysis | Extend existing `gpuprof.c` and bounded diagnostics for targeted shadow/light/water investigation. |
| Direct NVN HLE architecture | nxnative bypasses the guest graphics driver. This repository has a separate legacy NVN/Vulkan backend; the current APK uses ScarletNX. A new bridge is a larger optional project, not a drop-in patch or replacement authorized by the current preservation rules. |

Missing projected shadows, interior light shafts and water differences remain
unresolved. Supplied logs show shadow targets rendered and bound, not their
correct pixel contents. Do not call an optimization a visual fix without
device comparison or decisive pixel/semantic evidence.

Suggested investigation order (expected impact is a hypothesis, not a result):

| Next front | Expected impact / evidence needed | Change risk | Difficulty |
|---|---|---|---|
| Validate clear-load option | Unknown; count actual folds and compare equal-route frame intervals. | Conservative scope; driver validation pending. | Low: one APK, fresh-process OFF/ON. |
| Diagnose existing Android write-watch | Potentially high if full-content hashing remains expensive; measure availability and hash cost. | Low for diagnostics; high for a new fault-handler fallback. | Medium diagnosis / high implementation. |
| Repeated bindings, uploads and pass breaks | Potentially medium/high if CPU reconstruction or tile traffic dominates; use existing profiler/counters. | Medium to high depending on dependency scope. | Medium/high. |
| Shader prewarm/pipeline prediction | Mainly first-visit stutter; separate warm/cold-cache trials without deleting caches. | Medium; all variants must be correct. | Medium/high. |
| CPU scheduler/frame pacing | Unknown until CPU waits and stream intervals establish the bottleneck. | High if timing/scheduler semantics change. | High. |
| Missing visual effects / full bridge | Correctness priority; no FPS benefit assumed. Capture targeted pass pixels/resources. | High for resource/stage integration. | High. |

## Sources and build/test procedure

ScarletNX is pinned to `34853eeae5af132e320adbb0193f13344085bf89`. The actual
sources live in the user's `$HOME/.cache/lasrecomp-scarletnx-romfs/ScarletNX`;
LAS stores reversible patchers, not copies of that whole repository. Apply
and restore them in the order in `compilar-castlevania-shader-termux.sh`.

nxnative reference updated for the inventory to
`3eb1d76f5ddd56277f68fefbe162ec83a54899a1`. Relevant files are
`dm/gfx/nvn/nvn_mtl.m`, `nvn_dirty.c`, `nvn_pace.h`, `dm/gfx/README.md`,
`dm/gfx/tools/{cb_extent,dmsh_build,dmsh_fetch,tbdr_*}.py` and
`dm/host/hle_thread.c`. Adapt ideas to Vulkan/Android; do not copy Metal
libraries, game binaries, keys or private shader captures into the repository.

```bash
python3 -m unittest discover -s tests -p 'test_zelda_perf*.py' -v
bash -n compilar-castlevania-shader-termux.sh compilar-mario-snx-runtime-termux.sh compilar-zelda-fps-audit-termux.sh compilar-zelda-nxnative-termux.sh compilar-zelda-uniformes-termux.sh compilar-zelda-clears-termux.sh
git diff --check
```

Set `SCARLETNX_TEST_SRC` to the clean pinned checkout when it is not the test
default sibling `ScarletNX-audit`. Set `SPIRV_VAL` to a real executable
`spirv-val` to exercise the shader corpus validation. State skipped checks
explicitly. The actual source and fixtures exercise hashes, ownership,
transfer bytes, fence lifetime, patch rollback and log parsing on the host.

Termux update/build, without clearing anything:

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-clears-termux.sh
```

Use a warm cache and the same save, route, camera, resolution, refresh, cooling
and Stable60 state. Separate processes for OFF/ON; export 90-second logs and
compare matching complete windows after warmup. Preserve the last good APK.
Never compare capture+GPU-detailed sessions with LEVE and claim causality.

The latest delivery completed 29 audit tests with zero skips and a real
`spirv-val`, plus shell syntax, whitespace and the three full patched C-unit
syntax checks described in the clear scope. Settings for the C-unit checks
were generated from the pinned specification; LLVM option-table generation
is unnecessary for those units.
No full game/AOT rebuild was performed. A future test failure on Termux must
be fixed and recorded rather than dismissed because these host checks pass.
