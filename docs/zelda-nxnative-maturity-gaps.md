# Remaining nxnative advantages: verified code comparison

Updated 2026-10-24. The user asks what the more mature reference still has
that can improve this Zelda port. This is a source audit and prioritization;
it introduces no new runtime option, shader change, build or measured FPS.
The shadow-depth delivery remains at `491686e`, awaiting phone captures.

Follow-up: the user authorized implementation. The bounded stable-buffer
pool and passive WW diagnosis are now delivered; read
[`zelda-persistent-buffers.md`](zelda-persistent-buffers.md). This document's
initial table is the pre-implementation comparison. In particular,
`vk_own_res_new` pooling was already delivered by `9b405a6`; the new pool is
for `make_own`, not another copy of that transfer-result pool.

## Sources and scope

LASRecomp runtime/profile baseline: `491686ebe64bcc25ad6d289e4e82363d4690f3a7`.
Underlying ScarletNX: `34853eeae5af132e320adbb0193f13344085bf89`, with the
repository's reversible performance and graphics-diagnostic patches.

Checked the GitHub default-branch head of seedds/nxnative, then read these
files at **`7861e7c1a9913e020600b1cc7f65132427e9cc50`**:

- [`dm/gfx/nvn/nvn_mtl.m`](https://github.com/seedds/nxnative/blob/7861e7c1a9913e020600b1cc7f65132427e9cc50/dm/gfx/nvn/nvn_mtl.m)
- [`dm/gfx/nvn/nvn_dirty.c`](https://github.com/seedds/nxnative/blob/7861e7c1a9913e020600b1cc7f65132427e9cc50/dm/gfx/nvn/nvn_dirty.c)
- [`dm/gfx/nvn/nvn_pace.h`](https://github.com/seedds/nxnative/blob/7861e7c1a9913e020600b1cc7f65132427e9cc50/dm/gfx/nvn/nvn_pace.h)
- [`dm/gfx/README.md`](https://github.com/seedds/nxnative/blob/7861e7c1a9913e020600b1cc7f65132427e9cc50/dm/gfx/README.md)

The earlier inventory used `3eb1d76`. This newer review verifies the main
resource/argument/pipeline paths against the current source. Do not describe
every row below as a newly introduced upstream feature: most were already
present in the earlier reference. The latest commit fixes stencil-view usage
in Metal; that flag is not a direct Vulkan/Adreno performance patch.

## Already present here: do not port again

Our runtime already has shader persistence, background pipeline prewarm and
workers, asynchronous command recording, staging/readback rings, texture and
descriptor caches, buffer ownership tracking, batched uploads and GPU texture
conversion. The recent adaptations add transfer-result pooling/contiguous
copies, immutable graphics uniform snapshots, eligible full-clear load
actions, proven uniform prefixes and exact adaptive descriptor lookup.

The user positively reviewed transfer/uniform performance and later reported
aggregate improvements. Controlled device results remain pending for the
later clear/extent/binding steps. The 44-test shadow delivery is diagnostic;
its host checks do not establish a visual fix or FPS gain.

## Ranked remaining work

Expected benefit is a hypothesis from removed work, not a predicted FPS
percentage. Risk refers to the eventual implementation, not this read-only
source comparison. Some rows depend on earlier ones.

| Priority | Reference mechanism | Our actual gap | Benefit to establish | Risk / difficulty |
|---|---|---|---|---|
| 1 | Dirty-page generations: `nvn_dirty_since_span`, packaged-texture `stamp/seen/span` checks. | ScarletNX already has `vk_written_since`, generation tables and Linux async userfaultfd/PAGEMAP_SCAN; it was inactive in the supplied phone logs. Diagnose build headers, kernel facilities, permissions and alias/trap registration before designing a fallback. | Less complete-content hashing and CPU memory traffic for unchanged textures/buffers. | Low for reporting why unavailable; high / high for a new fault-handler path. |
| 2 | Persistent shared memory pools in `mtl_pool_add`, with first-use residency and deferred release. | Our staging and cache retention already exist, and transfer results now have a bounded retired pool. `make_own`/general `vk_own_res_new` allocation paths still need a separate audit for eligible additional reuse. | Fewer allocations/destructions and staging/promotional copies where they actually remain hot. | Medium / medium-high; prove references, fence retirement, generations and budget. |
| 3 | `args_sync_dirty`/`encode_args_`, texture serial/write generations, vertex-address cache. | Our binding fast path runs after full resource resolution and only saves descriptor hashes/lookup. It does not yet bypass repeated texture/buffer/view preparation using complete invalidation generations. | Less CPU work per repeated draw. | High / high; all CPU writes, DMA/compute writes, aliases, pool changes, feedback and frame lifetimes must invalidate correctly. |
| 4 | `NvPkg.spare`, `spare_fence` and batched uploads. | ScarletNX already batches copies/conversions and reuses images, but the inspected normal `tex_upload` refresh writes into the same image and ends rendering. Audit truly dynamic textures before adding a bounded second version. | Less serialization when updating an image still consumed by earlier work; fewer upload-induced pass breaks if dependencies permit. | Medium-high / high; preserve old in-flight pixels and every view/cache generation. |
| 5 | Full offline shader preparation, first-use manifests and `pso_predict_rest` bounded lookahead. | Native persistence/background prewarm already exists here. The remaining delta is broader unseen shader/variant coverage and useful ahead-of-demand preparation. | Fewer first-visit hitches; sustained warm-scene FPS may be unchanged. | Medium / medium-high; speculative work must not delay demanded pipelines or omit draws. |
| 6 | Partial/deferred uniform updates: `ubd_*`, `ubp_get`, `ubc_push`, overlap coverage and pending-write checks. | Snapshots and fixed-index prefixes are delivered. Broader partial composition/dynamic-range proofs are not. ScarletNX already publishes/batches inline updates, so another generic deferred-copy layer could be redundant. | Prepare fewer bytes and avoid additional pass breaks only in demonstrated residual cases. | High / high; exact command ordering, prior draws, GPU-written data and CPU observations must remain correct. |
| 7 | Cadence retention/no catch-up burst in `nvn_pace`; per-pass/texture GPU evidence and equivalence tests. | Our `present_pace`/Vulkan FIFO already pace frames. Physical Android scan-out evidence and a stable device pixel-regression set are missing; shadow capture is the first targeted pixel step. | More consistent delivered intervals and stronger protection against visual regressions. | Medium / medium; measure Android presentation before changing pacing. |
| 8 | Proven attachment load/store elimination and pass continuation/lookahead. | Our immediate clear folding and depth-read-only `STORE_OP_NONE` are partial existing coverage. Broader dependency/layer/alias/bindless proofs remain. | Lower attachment bandwidth on Adreno when a particular pass's work is proven redundant. | High / high; keep broad speculative elimination/merging off until observer coverage and pixel equivalence are proven. |

## Important distinctions

### Dirty tracking is an availability problem first

In `src/nx/gpu/vk/buffer.c`, `vk_written_since` falls back to content checks
when `plat_ww_scan` is unavailable. In `src/nx/runtime/platform/plat_posix.c`,
the Linux path is conditional on `PAGEMAP_SCAN`, `UFFD_FEATURE_WP_ASYNC` and
`UFFD_USER_MODE_ONLY`; runtime initialization/registration can fail too. A
missing compile-time UAPI macro and a denied kernel call need different fixes.
Neither is proven to be the specific phone failure yet. Do not claim that a
safe tracker is absent from the source, promise rootless availability, or
replace full hashes with weaker sampling to obtain a speedup.

### Persistent pools are not automatic zero copy on Android

nxnative wraps game pools with Metal `newBufferWithBytesNoCopy` in shared
storage. Vulkan on this Android driver does not automatically grant the same
capability over arbitrary guest allocations. A bounded buffer-retirement pool
is an independent candidate; importing/sharing guest memory needs extension,
coherence, alias and host-trap evidence. Keep the existing transfer pool and
staging rings; first measure allocations/copies outside their coverage.

### Do not equate all reference optimizations with production-safe settings

The current `tbdr_on()` still defaults the broad pass-optimization group OFF
because resource-read inference is incomplete for bindless textures. Its
cross-submission validity ledger's fallback can detect a missed reader after
that frame has already lost contents; probation is not a proof for all future
uses. That is insufficient to turn on broadly in this port with known missing
shadows/lights/water. Separately, nxnative has a narrower default-on rule for
attachments not written in a pass. Vulkan store semantics and observers need
their own validation; do not mechanically substitute Metal DontCare flags.

### The largest architectural difference is direct NVN interception

The reference takes over `nvnBootstrapLoader` and records/replays NVN calls
without executing the original graphics driver. Our active ScarletNX path
processes the Maxwell command stream generated by that driver. This is a
structural difference alongside Apple/Metal and Android/Adreno differences,
not evidence for a numeric transferable speedup. A direct NVN/Vulkan bridge
would be a separate large project, preserving the current runtime as the
working reference; do not silently replace this port or claim the partial
Ryujinx fragment translator supplies that architecture.

## Recommended next performance step and stopping point

Follow-up `0e0dfa4` delivered the bounded stable vertex/index/storage buffer
pool and passive tracker diagnosis. The first phone log confirms 7,184 pool
hits in 10,964 requests. It also establishes present UAPI definitions and
successful API negotiation followed by `/proc/self/pagemap` open denied
with errno 13. Measured texture-hash calls sum to 16.204 seconds over about
100 seconds of exported windows. Audit safe content verification/invalidation
under that observed app permission restriction; do not attempt to solve it
with header definitions. Broader resource-generation shortcuts still require
complete invalidation evidence. Clean OFF/ON FPS comparison remains pending
because both shader and shadow capture were enabled in this first log.

Keep the visual track separate: the shadow ZIP has now arrived and its maps
contain real geometry. It demonstrated a viewport-range mapping mismatch;
the capability-gated correction in [`zelda-depth-range.md`](zelda-depth-range.md)
is delivered for device OFF/ON testing. Lights, water/color and blur follow. See
[`zelda-performance-handoff.md`](zelda-performance-handoff.md) for the current
evidence and continuation point. No runtime changes or APK are delivered by
this inventory. No new tests
or full/AOT build are needed for these documentation-only changes. Future
code work must run the appropriate existing and new checks and leave another
continuation checkpoint. No measured Android improvement is claimed here.
