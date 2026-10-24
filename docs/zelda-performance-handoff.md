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

After the clear-load delivery the user said "Até agora só teve melhoras então
quero continuar com os port" and clarified that the requested next work is
nxnative-to-ScarletNX adaptation. This is positive aggregate feedback and
authorization to continue, not isolated clear OFF/ON measurements. Keep the
explicit uniform reference above, plus the newer `2cc5ce0` clear APK, available.

Build the latest reference with
`SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-uniformes-termux.sh`.
Output: `Download/ZeldaRecomp/Zelda-SNX-UNIFORMES.apk`.
Preserve that APK and `Zelda-SNX-NXNATIVE-TRANSFER.apk`. Keep transfer reuse
and uniforms ON, capture OFF, telemetry LEVE, the native translator and the
same Stable60 state when comparing the next independent option. If rebuilding
the uniform profile from newer code, explicitly keep the clear option OFF
and the uniform-extent option OFF for the reference trial; a saved ON
preference overrides the profile default. Keep binding reuse OFF too when
rebuilding that reference from newer code. Preserve the newer
`38355f1` extent APK as the immediate comparison for the binding delivery.
When rebuilding older references from the current source, also keep the new
**Reutilizar buffers persistentes** option OFF; a saved ON preference overrides
an older profile's OFF default.

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
| `2cc5ce0` | Optional eligible full clears as new-pass load actions, preserving same-pass reuse and conservative fallbacks. | 29 host tests pass; 40 old/new pixel-model scenes and full patched C syntax checks. Later aggregate user feedback was positive; isolated Android clear metrics remain pending. |
| `38355f1` | Optional proven prefixes for graphics uniforms, analyzed from the same new/cached SPIR-V. | 33 host tests pass; 61 synthetic native programs, strict snapshot bytes, actual persistent loader and full patched C syntax checks. No Android FPS result for this option. |
| `3dd1d57` | Exact, adaptive lookup of resolved descriptor state ahead of the existing hash cache. | 37 host tests pass; actual cache/recorder, 50 scenes / 3,200 bindings, sanitizer and full C syntax checks. Android FPS validation pending. |
| Shadow-depth evidence delivery (locate with `git log -1 -- tools/patch_scarletnx_zelda_shadow_capture.py`) | Optional bounded depth-aspect snapshots before shadow sampling, separate layer analysis and complete-session ZIP export. | Diagnostic only. First phone log reports three samples saved; exported pixels/ZIP pending. No visual fix or FPS gain claimed. |
| `0e0dfa4` | Exact-size reuse of completed stable vertex/index/storage buffers, plus passive write-watch failure evidence. | 49 host audit tests, actual source/lifetime/error paths, full C syntax and ASan/UBSan. First phone log confirms reuse and pagemap open denied; clean Android OFF/ON comparison pending. |

## Current stopping point: first buffer/WW phone evidence received; clean A/B and shadow ZIP needed

After the remaining nxnative maturity audit, the user said "Vamos la" and
authorized continuing the memory/resource work. Read
[`zelda-persistent-buffers.md`](zelda-persistent-buffers.md).

- Audit correction: `9b405a6` already pools every `VkOwnRes` allocation through
  `vk_own_res_new`; it is not merely a DMA-site cache. Do not repeat that port.
  The new scope is `buffer.c`'s `make_own` vertex/index/storage allocation and
  `drop_own` release. Staging rings, transfer pooling and snapshots remain.
- `tools/patch_scarletnx_zelda_ww_diag.py` applies after shadow capture, followed
  by `tools/patch_scarletnx_zelda_vb_pool.py`; restore in reverse order. WW is
  passive only: no new UAPI macros, probes, permissions, protections, kernel
  requests, tracking activation or relaxed hash checks. The first new phone
  log identifies a denied pagemap open, as recorded below. Sixteen fixed event slots preserve startup/errors without
  logging/allocating on those paths; renderer flushes them after PERF metadata.
- `SNX_WW_META_V1` reports native compile-header capabilities.
  `SNX_WW_EVENT_V1` distinguishes build guards, explicit environment disable,
  syscall/API negotiation, registration, pagemap open, remap and scan errors.
  A failed optional minor attempt can precede a successful existing fallback;
  read the sequence. No Termux probe stands in for APK permissions.
- Pool runtime `SNX_VK_VB_POOL=1`, UI **Reutilizar buffers persistentes**.
  Default ON only in the new buffer profile, honoring saved preferences.
  OFF + fresh process preserves original allocation/destruction policy.
  Exact sizes/unchanged usage, original frame-retirement completion, 64 idle
  entries/32 MiB actual VMA bytes and 300-frame expiry. Memory pressure can
  reclaim idle buffers. Metadata/staging/allocation failures retain safe
  original paths. Hashes, copies, barriers and `buf_get` remain unchanged.
- `SNX_VB_POOL_META_V1` / `SNX_VB_POOL_V1` count real allocation attempts,
  successes/failures, hits and lifetime transitions; bytes/entries are gauges.
  The analyzer requires complete same-mode windows and keeps WW evidence.
  Neither allocation counts nor host models establish a phone FPS gain.
- Build `SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-buffers-termux.sh`;
  output `Download/ZeldaRecomp/Zelda-SNX-BUFFERS.apk`. Prior bindings APK has
  a once-only `Zelda-SNX-BINDINGS-ANTES-BUFFERS.apk` backup; other references,
  shader caches, Stable60 and AOT stay. FSWZADD remains OFF.
- Device test: capture shadows/shaders OFF, LEVE, equal route/configuration;
  separate 90-second fresh-process Buffers OFF/ON runs, then export both logs.
  They provide both pool/frame measurements and actual tracker failure stage.
- 49 audit tests pass, zero skips, real `spirv-val`; actual source under
  delayed GPU/retirement models preserves data through 50 scenes/150 copies.
  The controlled ON model uses 3 allocations/147 hits vs 150 allocations OFF,
  with identical copies/pass ends/bytes. Eighteen before/after POSIX scenario
  pairs preserve syscalls, callbacks and fallback/error results. ASan/UBSan,
  three full patched C-unit syntax checks and changed Java syntax pass.
  No Android APK/game/driver run or FPS improvement was measured here.

### First phone evidence from `0e0dfa4` (2026-10-24)

Uploaded `Zelda-SNX-boot (1).txt`, SHA-256
`5c9d7e6f6a156dce187a4f1267cefede037737a90799f8920fa41d77f93b4af3`.
The raw private upload stays outside the repository. The exported file repeats
some startup/error lines; totals below use its one `SNX PERF BEGIN` block,
20 complete windows / 100.160987 seconds, without counting those duplicates.

- Revision is `0e0dfa4c6a89470b095ccc74f03cbdbf2a715ac1`, native ScarletNX
  translator (`ryujinx_requested=0`), pool ON. All prior performance options
  report ON. There is no matched pool-OFF run in this upload.
- The tracker has all four build capabilities. `api_ready` succeeds, then
  `pagemap_open_failed` reports errno 13 (`EACCES`) opening
  `/proc/self/pagemap`. The original code unregisters its WP range and uses
  content verification. This is an application-context permission denial,
  not missing UAPI declarations or a rejected userfaultfd API negotiation.
  The log does not identify the precise policy responsible (for example,
  no AVC evidence is supplied). Do not add header shims, bypass permissions
  or treat this as successful write tracking.
- Stable-buffer work counters: 10,964 requests, 7,184 pool hits (65.52%),
  3,780 allocation calls, zero allocation/staging failures. The largest
  *reported idle-pool gauge* is 1,452,800 bytes (not total live GPU memory
  and not a guaranteed between-window peak). This confirms actual reuse in
  this run; it does not establish a before/after frame-time gain.
- Measured texture-hash call durations sum to 16,204.259 ms, checking
  220,543,965,184 logical bytes (205.40 GiB). These are repeated content
  checks, not unique resident texture bytes or physical DRAM traffic.
  This is substantial remaining work and motivates auditing the denied-
  tracking fallback and texture invalidation. Preserve all content checks
  until an equally complete write/alias/CPU/GPU observer strategy is proven.
- JIT wait/compile/failure counters are all zero in the exported windows;
  startup queues 24 previously discovered PCs, which alone is not evidence
  of a gameplay JIT bottleneck. Pipeline making totals 665 ms, waits 466 ms;
  late individual frames report 132 ms and 182 ms waiting for pipelines.
  Shader translation totals 42 ms. Neither explains every slow window.
  Timeline/pace measurements overlap across threads and must not be added
  together or interpreted as pure GPU execution time.
- Shader capture is ON: `SNX_SHADER_CAPTURE_V1` explicitly bypasses
  translated-shader persistence, while the separate Vulkan pipeline cache
  loaded 4,537 KB. Do not claim all caches are absent or broken. Shadow
  capture is also armed and saved three 16-MiB samples. The normal analyzer
  correctly rejects this session for FPS comparison. Raw stream rates are
  descriptive only; a later 5-second window reports 46.668 rendered frames/s
  despite only 2 ms pipeline making, and several others report about 60.
  `present_enqueue` is not physical Android display/scan-out feedback.
- All three shadow samples report saved (frames 764, 1656, 2541, one layer
  each); pixel files were not attached. Export **Exportar diagnostico de
  sombras (.zip)** before another captured run replaces the latest session.
  Saving depth data alone does not establish correct projected shadows.

**Resume:** obtain the existing shadow ZIP for pixel analysis and separate
fresh-process pool OFF/ON logs with both captures OFF and telemetry LEVE;
no rebuild is needed just to change those options. Then compare allocation
counts with frame p95/p99. For memory work, audit a safe Android content-
verification/invalidation path under the observed pagemap denial rather than
assuming headers can activate tracking. Dynamic textures, shader coverage,
partial updates and pacing remain. Missing shadows/lights/water stay on the
independent visual track below; the latest diagnostics have not fixed them.

## Visual track: three depth samples reported saved; shadow ZIP/pixels needed

The earlier user request prioritizes missing shadows, lights and water using
nxnative as the reference. Read [`zelda-shadow-depth.md`](zelda-shadow-depth.md)
when continuing that independent track; performance changes do not prove a
visual correction. The user subsequently authorized the buffer/WW step above.

- Existing shader captures were already analyzed; do not re-run the rejected
  FSWZADD experiment. The supplied log has shadows ON and real 2048x2048 D24S8
  2D-array shadow views. Existing traces show setup/bind activity, not pixels.
- nxnative explicitly handles NVN depth mode and lower-left origin; ScarletNX
  already has corresponding viewport, vertex-depth and facing logic. Native
  VS/CS translation also exists. Do not blindly copy synthetic HLE driver
  constant tables or treat missing full Ryujinx stages as the proven cause.
- `tools/patch_scarletnx_zelda_shadow_capture.py` applies after binding reuse
  and restores first. Runtime `SNX_SHADOW_CAPTURE_DIR` is a new private session
  path passed only on opt-in. **Capturar sombras (3 amostras; teste visual)**
  defaults OFF. Independent of shader capture and all performance switches.
- Capture at first eligible nonindexed real shadow-depth sampling from 15 s
  after init, then at least 15 s apart, three maximum. All base-level array
  layers at actual scaled dimensions; one pending buffer <=64 MiB. Original
  image use is restored and the original sample transition still runs. No
  extra explicit GPU wait/submit, shader edit, guest write or cache change.
- Normal frame-retirement callback invalidates and saves private raw depth +
  metadata. JSON is committed last; newest-session ZIP export never mixes
  stale successes into an empty current run. Raw Vulkan D24 depth copies are
  X8_D24, not guest interleaved D24S8. The analyzer masks undefined high bits.
- This diagnostic adds transfer/pass/disk costs; no FPS comparison while ON.
  The FPS analyzer rejects armed sessions. OFF + a fresh process reverses
  runtime diagnostic work without another build. Existing reference APKs and
  all performance ports/Stable60/AOT/caches remain available.
- Build: `SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-sombras-termux.sh`.
  Output `Download/ZeldaRecomp/Zelda-SNX-SOMBRAS.apk`. A once-only backup of
  the prior bindings APK is `Zelda-SNX-BINDINGS-ANTES-SOMBRAS.apk`.
- Request one outdoor 60-second same-scene run with capture ON, LEVE, native
  translator and shader capture OFF, then **Exportar diagnostico de sombras
  (.zip)** plus a screenshot. Disable capture afterwards. No phone snapshot
  from this delivery has yet been supplied; do not claim restored effects.
- Host validation: 44 audit tests pass, zero skips, including the real Java
  exporter compiled for Java 8, native delayed capture/format tests and the
  byte-exact complete patch stack rollback. Real `spirv-val` remains enabled.
  Full patched `render.c`/`renderer.c` syntax and ASan/UBSan pass. LeakSanitizer
  is unavailable under this host's `/proc` restriction. No Android APK or
  device/game run was performed here.

**Resume:** inspect each captured layer's pixels and the matched producer
registers/consumer descriptors. Empty/constant or wrong-layer/orientation maps
lead to producer/rasterization/clear/layer investigation; plausible maps lead
to consumer coordinates, depth reference and sampler comparison. Constants
can be legitimate: establish the scene and intended layers before a repair.
Then trace interior light culling/composition; then water's depth/normal/
environment/reflection/composition. Keep corrections small and reversible.
Performance binding/extent/clear A/B measurements are still pending separately.

## Previous maturity audit: remaining nxnative advantages

After the shadow diagnostic, the user asks what the more mature reference
still has that can improve performance. This follow-up is an inventory, not
authorization to call any unmeasured item a speedup or a delivered runtime
patch. Read [`zelda-nxnative-maturity-gaps.md`](zelda-nxnative-maturity-gaps.md).

- Rechecked GitHub: nxnative default-branch head was
  `7861e7c1a9913e020600b1cc7f65132427e9cc50`. Read current `nvn_mtl.m`,
  `nvn_dirty.c`, `nvn_pace.h` and `dm/gfx/README.md`. Earlier source references
  at `3eb1d76` remain historical; this comparison updates these four files.
- Strongest source gaps: available/reliable dirty-page tracking on Android;
  broader lifetime-safe persistent buffers; resource/argument reuse before
  repeated construction; dynamic texture versions; broader offline shader
  variants/lookahead; residual partial uniform work; Android pacing/pixel
  verification; proven additional attachment bandwidth reductions.
- ScarletNX already implements dirty tracking, prewarm, async recording,
  staging/descriptor/texture caches and batched GPU conversions. Do not
  recreate them. Supplied logs had tracking inactive: first diagnose UAPI
  build guards vs kernel/permissions/registration, retaining full checks.
- Next bounded performance-port candidate remains general owned-buffer
  allocation/release reuse beyond the delivered transfer pool. Measure its
  remaining allocations/copies before changes. Broader generation shortcuts
  need complete CPU/GPU/alias invalidation and resource lifetime proofs.
- nxnative's Metal shared no-copy pools are not a guaranteed Android Vulkan
  facility. Its broad TBDR pass optimization group is still OFF by default;
  the bindless/observer gaps prevent treating it as a safe ready-made port.
- The direct NVN interception architecture is a separate large optional
  project. Keep the working ScarletNX/Stable60 path; do not replace it as an
  incidental optimization. Missing shadows/lights/water and shadow capture
  validation remain pending, independent of this performance inventory.
- Documentation-only follow-up: no new runtime, APK, test/FPS claim or AOT
  rebuild. Last code validation remains the 44-test shadow delivery above.

## Previous binding-state delivery; device A/B still pending

The user said "Bora pra.proxima" after the extent delivery and authorized
continuing nxnative ports. No isolated extent or new binding FPS log arrived.
This delivery adapts nxnative's encoded-argument reuse idea conservatively:
all ScarletNX resource resolution still runs; repeated exact resolved state
can bypass the two descriptor hashes. Read
[`zelda-binding-reuse.md`](zelda-binding-reuse.md) before continuing.

- Implemented in `tools/patch_scarletnx_zelda_bind_reuse.py` and
  `tools/zelda-perf/bind_reuse.h`. Apply after uniform-extent; restore before it.
- Runtime `SNX_VK_BIND_REUSE=1`; UI **Reutilizar bindings validados**.
  Defaults ON only in the binding profile; saved preferences override it.
  OFF and a fresh game process reverses this step independently.
- Existing descriptor cache, `cb_get`, texture/view/sampler reuse, async set
  recording, pool retention and `g_dyn` suppression already existed. Do not
  implement them again. The entire `stage_set` body remains byte-identical.
  Strict reads, pending GPU writes, uploads, storage/feedback state and
  barriers are resolved before the new lookup.
- Ten bounded layout states compare every write header and descriptor value,
  excluding padding/temporary pointer addresses. Only the original frame
  lifetime is accepted. Unknown/chained/oversized shapes keep the old cache;
  failed creation or a frame change during creation is not retained.
- An entry warms only after two original lookups of its layout/frame return
  the same set. Changing uniforms pay no repeated complete-key copy. Exact
  comparisons stop at the first mismatch; a hit avoids only hashing/lookup.
  This is the first binding adaptation, not broad generation-based skipping
  of resource-state construction. No shader/cache/AOT ABI or draw change.
- `SNX_BIND_REUSE_META_V1` / `SNX_BIND_REUSE_V1` count lookups, fast_hits,
  original_lookups, key_refusals, key_bytes_built, hash_mix_calls_bypassed and
  states_saved. Key refusals are rejected key attempts, not all unsupported
  requests. Counts are CPU work evidence, not milliseconds/GPU time/FPS.
- `compilar-zelda-bindings-termux.sh` produces `Zelda-SNX-BINDINGS.apk`,
  validates five current profile assets/runtime markers and preserves the
  extent/clear/uniform/transfer APKs. An existing extent APK gets a once-only
  `Zelda-SNX-UNIFORMES-ALCANCE-ANTES-BINDINGS.apk` backup. Existing AOT/build
  and shader caches are reused; FSWZADD remains OFF.
- 37 audit tests pass, zero skips, with a real `spirv-val`. The actual cache,
  recorder packets/callbacks, stand-in resolver and pool-reset path replay
  3,200 bindings across 50 synchronous/asynchronous scenes. Contents remain
  equal after caller data is overwritten. Exact removed hash-call counts,
  adaptive misses, array counts/fields, frame recycling/creation change and
  failures are exercised. Five full patched C units pass syntax checks.
  ASan/UBSan pass; host LeakSanitizer is unavailable under the `/proc` task
  restriction. No Java/Android APK, driver or game run was performed here.

**Performance resume after visual work:** inspect binding OFF/ON phone evidence if available, with every
other option equal, capture OFF and LEVE. Compare fast_hits/original_lookups,
frame p95/p99 and existing profiles. A low hit rate can outweigh the saved
hashing; do not call work counters an FPS gain. Do not reimplement this lookup.
The next independent port candidate is broader persistent buffer reuse beyond
the transfer pool. First audit existing staging/owned-buffer reclamation and
prove aliases, generations and fence retirement before adapting it. Broad
resource dirty-generation fast paths and partial GPU updates remain pending.

## Previous proven-uniform-prefix scope and validation

The user selected continuing nxnative ports, specifically the remaining
uniform update work. Audit found that Metal-style deferred GPU copies are
not present in the same form here: ScarletNX already publishes inline updates
through `gmem_write`, batches words and now uses immutable graphics snapshots.
Do not add a redundant deferred-copy layer or delay guest-visible writes.

The selected new adaptation comes from nxnative's `cb_extent.py`/`ubp_get`:
prove the prefix the shader can read, avoiding full 64-KiB preparation for
fixed-address LDCs whose native `cbuf_max` remains 65536. See
[`zelda-uniform-extents.md`](zelda-uniform-extents.md) before changing it.

- Implemented in `tools/patch_scarletnx_zelda_ub_extent.py` and
  `tools/zelda-perf/ub_extent.h`; apply after clear-load, restore before it.
- Runtime `SNX_VK_UB_EXTENT=1`; UI **Alcance comprovado dos uniformes**.
  Defaults ON in extent/binding profiles; saved preferences override it.
  All previous options remain independent. Each OFF/ON trial needs a fresh
  game process, not a second build.
- Only canonical scalar uniform access chains with exact constant indices
  (including supported exact 32-bit expressions) are proven. Dynamic indices,
  specialization values, unknown pointer uses, escapes, vector/block loads,
  aliases of a binding and unsupported layouts keep the original range.
  Every pointer use is audited across the whole module. Allocation/framing
  failures fall back. Already bounded native banks and compute skip analysis.
- Proofs live only in transient `VkSh` fields. Original `ShaderInfo`,
  `PfShader`, SPIR-V instructions and cache path/key/format are unchanged.
  New compilation and the actual persistent loader calculate the same proof.
  No cache deletion or forced shader retranslation is added.
- Graphics binding size uses the smaller proven prefix only after the old
  guest/native/device bounds. All strict hashes, visibility, ownership and
  immutable lifetime rules still apply to every selected byte. No AOT/CPU
  ABI change, skipped draw, resolution change or removed wait/barrier.
- `SNX_UB_EXTENT_META_V1` / `SNX_UB_EXTENT_V1` expose bindings,
  reduced_bindings, requested_bytes and bound_bytes. These are binding-range
  sums, not measured uploads, bandwidth saved or FPS. Compare existing staging
  counters and frame p95/p99 in complete matching windows.
- `compilar-zelda-uniformes-alcance-termux.sh` validates four current assets
  and compiled runtime markers, producing `Zelda-SNX-UNIFORMES-ALCANCE.apk`.
  It preserves clear/uniform/transfer APKs and backs up an existing clear APK
  once as `Zelda-SNX-CLEARS-ANTES-ALCANCE.apk`. Reuses existing AOT/caches;
  FSWZADD stays OFF.
- 33 audit tests pass with a real validator. New coverage uses the actual
  decoder/translator/emitter, native binding-size code, strict snapshot
  functions, actual cache loader and record types. Sixty-one synthetic
  programs exercise fixed/dynamic/mixed LDCs. Fifty-four modules are validated;
  original shader words, saved metadata and old draw bytes remain unchanged.
  Failure paths and 512 corrupt-word mutations are also exercised. Four full
  patched C units pass syntax checks. No Android APK/game run on this host.

Extent validation remains pending: inspect OFF/ON device logs with previous options equal,
capture OFF and LEVE. Check that `reduced_bindings` is nonzero, compare uniform
staging/hash work and frame intervals; do not infer FPS savings from range sums.
Do not implement this proof twice. General deferred GPU updates, dynamic-index
interval analysis and partial uniform-write shadows are still unimplemented.
The first binding lookup adaptation is now delivered above. Broader persistent
buffer pools and resource dirty-generation fast paths remain candidates;
preserve ownership/lifetime proofs. Android write-watch diagnosis remains in
the inventory, but was not the user's selected port for these deliveries.

## Previous clear-load scope and validation

The first uniform adaptation is implemented, host-validated and now positively
reviewed by the user. The next adaptation is implemented in
`tools/patch_scarletnx_zelda_clear_load.py` and `tools/zelda-perf/clear_load.h`.
The user explicitly asked to resume from the exact stopping point without
redoing existing work. Do not rewrite the transfer/uniform implementations
or restart the nxnative audit. Read [the clear scope](zelda-clear-load.md)
and check whether device logs/feedback for this delivery have arrived first.

- Option: `SNX_VK_CLEAR_LOAD=1`, **Limpezas completas no inicio do passe**.
  Default ON in clear/extent/binding profiles (saved preference respected);
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

Clear validation remains pending: inspect OFF/ON phone evidence for this option, with
transfers/uniforms ON and capture OFF. Check `folded_commands`, frame p95/p99
and visuals; maintain the last approved `d212126` reference until validated.
Do not transplant fault handlers or shared pools without the alias/ownership
proofs listed below. Broader partial/deferred clears and load/store elimination
remain separate, unimplemented work. The newer uniform extent work above
continues from this checkpoint without rewriting it.

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
  `Uniformes em snapshots reutilizaveis`. Defaults ON in uniform/clear/extent/
  binding profiles, OFF in the ordinary audit/transfer variant unless the user has
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
| Graphics uniform snapshots and small updates | Snapshots positively reviewed on device; proven fixed-index prefixes now delivered with device metrics pending. Full deferred GPU updates/partial shadows and dynamic-index proof remain separate work. |
| Android dirty-page tracking | First `0e0dfa4` phone log: build capabilities present and API negotiation succeeds, but `/proc/self/pagemap` open fails with `EACCES`; original content checks remain. Audit the safe fallback/invalidation path under that actual restriction, preserving aliases, host writes and GPU ownership traps. Header compatibility is not the observed problem. |
| Broader persistent/shared GPU pools | `VkOwnRes` pool and new exact-size stable-buffer retirement pool are delivered; new phone A/B pending. A whole-pool shared-memory path still needs Vulkan/driver support, alias and lifetime proofs. |
| Binding/state fast paths | Exact adaptive descriptor lookup now delivered; device metrics pending. Full resource reconstruction remains unchanged. Broader dirty-generation fast paths still need observer proofs. |
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
| Per-pass pixel capture and bandwidth/dependency analysis | First bounded shadow-depth capture is delivered; collect outdoor layers. Color/light/water pass captures and broader bandwidth analysis remain. |
| Direct NVN HLE architecture | nxnative bypasses the guest graphics driver. This repository has a separate legacy NVN/Vulkan backend; the current APK uses ScarletNX. A new bridge is a larger optional project, not a drop-in patch or replacement authorized by the current preservation rules. |

Missing projected shadows, interior light shafts and water differences remain
unresolved. Supplied logs show shadow targets rendered and bound, not their
correct pixel contents. Do not call an optimization a visual fix without
device comparison or decisive pixel/semantic evidence.

Suggested investigation order (expected impact is a hypothesis, not a result):

| Next front | Expected impact / evidence needed | Change risk | Difficulty |
|---|---|---|---|
| Validate binding reuse | CPU descriptor hashing only; actual hit rate/frame intervals decide. | Conservative exact state/lifetime scope; device validation pending. | Low comparison; broader generation paths are harder. |
| Validate uniform-extent option | Unknown; actual reduced bindings, staging/hash work and equal-route frame intervals decide. | Conservative proof/fallback; driver validation pending. | Low: one APK, fresh-process OFF/ON. |
| Validate clear-load option | Unknown; count actual folds and compare equal-route frame intervals. | Conservative scope; driver validation pending. | Low: one APK, fresh-process OFF/ON. |
| Diagnose existing Android write-watch | Potentially high if full-content hashing remains expensive; measure availability and hash cost. | Low for diagnostics; high for a new fault-handler fallback. | Medium diagnosis / high implementation. |
| Repeated bindings, uploads and pass breaks | Potentially medium/high if CPU reconstruction or tile traffic dominates; use existing profiler/counters. | Medium to high depending on dependency scope. | Medium/high. |
| Shader prewarm/pipeline prediction | Mainly first-visit stutter; separate warm/cold-cache trials without deleting caches. | Medium; all variants must be correct. | Medium/high. |
| CPU scheduler/frame pacing | Unknown until CPU waits and stream intervals establish the bottleneck. | High if timing/scheduler semantics change. | High. |
| Missing visual effects / full bridge | Current priority: bounded shadow-depth capture is delivered; inspect its phone evidence, then lights and water. No FPS benefit assumed. | Low opt-in evidence; high for resource/stage changes. | Medium diagnosis / high repairs. |

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
bash -n compilar-castlevania-shader-termux.sh compilar-mario-snx-runtime-termux.sh compilar-zelda-fps-audit-termux.sh compilar-zelda-nxnative-termux.sh compilar-zelda-uniformes-termux.sh compilar-zelda-clears-termux.sh compilar-zelda-uniformes-alcance-termux.sh compilar-zelda-bindings-termux.sh compilar-zelda-sombras-termux.sh compilar-zelda-buffers-termux.sh
git diff --check
```

Set `SCARLETNX_TEST_SRC` to the clean pinned checkout when it is not the test
default sibling `ScarletNX-audit`. Set `SPIRV_VAL` to a real executable
`spirv-val` to exercise the shader corpus validation. State skipped checks
explicitly. The actual source and fixtures exercise hashes, ownership,
transfer bytes, fence lifetime, patch rollback and log parsing on the host.

Termux update/build for the current buffers/WW profile, without clearing anything:

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-buffers-termux.sh
```

Use a warm cache and the same save, route, camera, resolution, refresh, cooling
and Stable60 state. Separate processes for OFF/ON; export 90-second logs and
compare matching complete windows after warmup. Preserve the last good APK.
Never compare capture+GPU-detailed sessions with LEVE and claim causality.

The latest delivery completed 49 audit tests with zero skips and a real
`spirv-val`, plus shell syntax, whitespace, Java exporter execution/changed
activity syntax and three affected full patched C-unit syntax checks. The previous binding
scope checked five C units. Settings for the C-unit checks were generated
from the pinned specification; LLVM option-table generation is unnecessary
for those units.
No full game/AOT rebuild was performed. A future test failure on Termux must
be fixed and recorded rather than dismissed because these host checks pass.
