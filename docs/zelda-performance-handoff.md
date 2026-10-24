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

**Latest visual reference: the `9be351c` depth delivery.** The user now reports
colors and water resolved. New photos show tree/character shadows and some
depth-of-field blur; the user still reports missing shadow/reflected light,
outdoor haze and interior window shafts. Preserve `Zelda-SNX-PROFUNDIDADE.apk`
and its current options. The lighting-diagnostic wrapper backs it up once as
`Zelda-SNX-PROFUNDIDADE-ANTES-ILUMINACAO.apk`. No new revision/toggle/capability
log or controlled FPS comparison accompanied those photos; their 57/60/59
phone overlays alone do not establish stable 60 FPS or full visual parity.

**Earlier qualitative FPS approval: `0e0dfa4`**, the persistent-buffer APK.
Along with the shadow ZIP, the user said the FPS improved substantially but
shadows, water/colors and some blur remain wrong. This is aggregate feedback,
not an isolated measured pool speedup. Preserve that APK as the immediate
reference for the viewport-depth correction; keep its performance options.
`Zelda-SNX-BUFFERS-ANTES-PROFUNDIDADE.apk` is the new wrapper's once-only backup.

**`d2121261bb83ed2edcbde0882431d1d2ce7bee0d`** remains an earlier explicitly
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

Build that earlier uniform reference with
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
Also set **Preservar faixa de profundidade OFF** when rebuilding any earlier
comparison after saving that new option ON; older profile defaults do not
override saved preferences.

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
| Shadow-depth evidence delivery (locate with `git log -1 -- tools/patch_scarletnx_zelda_shadow_capture.py`) | Optional bounded depth-aspect snapshots before shadow sampling, separate layer analysis and complete-session ZIP export. | Three phone depth maps received/analyzed, with actual geometry. Diagnostic itself is not a fix or FPS gain. |
| `0e0dfa4` | Exact-size reuse of completed stable vertex/index/storage buffers, plus passive write-watch failure evidence. | 49 host audit tests, actual source/lifetime/error paths, full C syntax and ASan/UBSan. First phone log confirms reuse and pagemap open denied; clean Android OFF/ON comparison pending. |
| `9be351c` | Preserve computed finite depth endpoints with the explicitly requested/advertised Vulkan extension, retaining original shaders and OFF fallback. | 53 host tests. User reports colors/water resolved and photos show partial shadows/blur; haze, shafts and residual shadow/light remain. Exact new capability log pending. |
| `3d0b426` | Bounded raw/effective first-color raster/blend state and separately budgeted valid 2D color-RT inputs in existing GPU detailed mode. | Both new scene logs received: depth fix actually enabled, candidates/state/input views present. No demonstrated blend fault. |
| Paired effect-depth evidence (locate with `git log -1 -- tools/patch_scarletnx_zelda_effect_depth.py`) | Independent default-OFF capture of actual attachment/sample depth planes for four observed fragment candidates, at most three paired snapshots. | 61 host tests, actual surface barriers/Java exporter, full C syntax, ASan/UBSan. New phone pixel evidence pending; this is not a new lighting repair. |

## Current stopping point: both lighting logs analyzed; paired depth-pixel evidence ready

Read [`zelda-effect-depth-evidence.md`](zelda-effect-depth-evidence.md) first.
The requested two scene logs **have arrived and are analyzed**. Do not ask
the user to repeat the same GPU detailed logs or old shader/shadow ZIP.

- Both revision `3d0b426`, all prior performance options ON (Ryujinx live/cache
  OFF), new depth extension requested/supported/enabled. Shader/shadow capture
  not armed. Pagemap open still EACCES. JIT counters zero. Vulkan pipeline
  cache loaded (4450 KB); the inactive Ryujinx persistence flag is not the
  native cache's enabled state.
- Native render rates after the first 10 seconds are 60.000 over 20.033 s
  outside and 59.404 over 50.081 s in the house. These GPU detailed sessions
  include scene movement and are not baseline comparisons, game simulation,
  physical display FPS or proof of a gain/stable 60 everywhere.
- Full window state/RT records: outdoor 384/360, house 663/636. State limits
  reached in 6/6 and 5/12 windows. Partial final graphics windows exist; do
  not count them as complete performance windows. Only parse the one PERF
  block to avoid repeated startup/tail rows.
- House additive/alpha composition states are coherent in the recorded
  scope; no blend/alpha/gamma change is established. Candidates
  `86d5a3f915a6795f`, `2957c0d7d6264a3a`, `7444fc6ce498b4bf` and outdoor
  `9f178ae97683fd4e` read noncomparison scene-depth copies at slot 0. They
  already match the private shader corpus. Data/age/producer and actual
  light pixels remain unknown. A real view does not prove correct contents.
- New `patch_scarletnx_zelda_effect_depth.py` applies after LIGHTING and
  restores first. OFF does no inspection. ON captures a distinct active
  depth attachment plus the sampled depth, same actual dimensions/format,
  one mip/layer, D24/D32 only. One combined <=64 MiB mapped buffer pending,
  at most 3 pairs >=15 s apart, existing barriers and retirement callback,
  no extra explicit waits/submits/guest writes/shader changes. Relationship
  remains explicitly **unproven**, not a claimed source/destination lineage.
- Builder `SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-efeitos-termux.sh`;
  output `Download/ZeldaRecomp/Zelda-SNX-EFEITOS-DEPTH-DIAG.apk`, prior
  lighting APK saved once as `Zelda-SNX-ILUMINACAO-ANTES-EFEITOS.apk`.
  New asset-gated **Capturar profundidade de luz/nevoa (3 pares)** OFF by
  default. For capture: turn it ON, shadow/shader captures OFF, FPS LEVE,
  depth preservation ON and existing performance options. Stay 60 s in
  the house; export its new ZIP. A fresh outdoor session can supply the
  second ZIP. Return capture OFF and restart for normal play.
- New analyzer `tools/analyze_zelda_effect_depth.py` validates paired plane
  offsets/bytes, bounded same-session ZIPs and undefined D24 bits. It prints
  per-plane depths/differences and optional previews, never "difference=bug".
  The FPS analyzer rejects armed effect capture. Separate bounded export
  namespace preserves old shadow captures and newest-session semantics.
- 61 host audit tests pass (zero skips with real SPIR-V validation), actual
  surface-use lifetime/failure tests, whole stack exact rollback, Java
  export, ASan/UBSan, full C syntax, Java parsing and shell/Python checks.
  No Android APK or actual GPU pixel result is available on this host.

**Resume:** inspect the new paired pixels. If plausible, inspect candidate
uniform/projection/art-texture/color outputs. If unexpectedly different,
establish actual copy lineage before changing synchronization/lifetimes.
Keep colors/water accepted as resolved. Remaining: haze, interior shafts/
reflected light, residual shadows/local blur, then separate copy-gap/hash
performance work with proper LEVE A/B. No speculative FSWZADD or global
brightness/blend adjustment.

### Previous stopping point, superseded by the scene logs above

Read [`zelda-lighting-composition.md`](zelda-lighting-composition.md).
The user supplied three post-depth-delivery photos and reports colors/water
resolved, while asking about haze, shadow/reflected light and indoor shafts.
Projected shadows and foreground blur are visibly present in part. Do not
reclassify the whole shadow system/blur as absent or water as still broken.

- Keep the improved `9be351c` visual reference, all performance ports and
  **Preservar faixa de profundidade ON**. Existing shadow ZIP/source analysis
  is complete; do not ask for the same initial shader/depth captures again.
- The original detailed diagnostic suppresses ordinary valid 2D color reads
  and does not log blend/constants/alpha/stencil/viewport state. It cannot
  establish the failing composition input or state. Preserve its original
  pass/binding budgets while adding independent bounded evidence.
- `tools/patch_scarletnx_zelda_lighting_diag.py` applies after DEPTH_RANGE and
  restores first. No new visual toggle: uses the existing GPU DETALHADA mode.
  LEVE/OFF returns before observer inspection. Raw state plus effective blend
  and selected depth range are recorded, as are valid nonindexed 2D color RT
  inputs. No resource resolution, shader/render/cache/sync change or GPU work.
- `SNX_LIGHT_STATE_V1` records up to 64 exact state families per window,
  printing the first target example and first bound color slot. Target
  identity/dimensions are not the signature: this is not a complete render
  graph. `SNX_LIGHT_RT_V1` has a separate 64-entry budget and full TIC/TSC.
  Existing depth/non-2D/missing-view tracing remains. Limits/refused lines and
  attempt counts are explicit; setup/descriptor evidence does not prove pixels.
- Audit rejected a blind nxnative `bfac` port: its NVN API constant-color/
  alpha IDs 0x61..0x64 are not the Maxwell register encodings. Official NVIDIA
  register mappings already present here include D3D 0x0e/0x0f and OGL
  0xc001..0xc004. No observed raw 0x61 defect or blend change is established.
- Build `SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-iluminacao-termux.sh`;
  output `Download/ZeldaRecomp/Zelda-SNX-ILUMINACAO-DIAG.apk`. The depth APK
  is backed up once; AOT/Gradle/CMake/Ninja/shader caches are reused. Install
  update, capture shaders/shadows OFF, native translator, current options.
- Select GPU DETALHADA. Stay about 45 seconds in the telephone house, exit
  normally, export `Zelda-luz-casa.txt`. In a fresh process repeat at the forest
  haze comparison spot and export `Zelda-nevoa.txt`. Then return logging to
  LEVE for normal play. No FPS comparison between detailed and LEVE runs.
- 57 host audit tests pass, zero skips with real spirv-val; actual observer
  inputs remain byte-identical, OFF has no inspection/logs, changes stay
  distinct, separate bounds/reset hold, signed-APK gates and whole-stack
  apply-twice/byte-exact rollback pass. Native ASan/UBSan and full render/
  renderer C syntax pass. Actual Java exporter preserves 139 generated rows,
  including 1,254-byte rows, intact. No new Android APK/game result claimed.

**Historical next step (completed above):** inspect fresh capability/state/input logs from the corrected build;
old detailed logs predate it. Identify the actual haze/shaft or residual-shadow
consumer and its state/inputs before changing blending, shaders or depth again.
Use already captured matching shader programs; request only missing evidence.
If setup looks plausible, bounded color-pixel evidence may still be needed.
Colors/water are accepted as improved; do not undo them. Remaining visual work:
haze, indoor shafts/reflected light, residual shadowing and localized blur
differences. Memory/hash work and clean FPS A/B remain independent.

## Previous depth stopping point: maps analyzed and viewport correction delivered

Read [`zelda-depth-range.md`](zelda-depth-range.md) before the next change.
The user supplied the requested `Zelda-sombras.zip`; do not ask for that same
ZIP again or restart the earlier producer-versus-consumer audit.

- The ZIP has three complete real D24 depth maps, with matching recorded
  producer generations. Maps 1 and 3 contain recognizable outdoor geometry;
  map 2 has a smaller silhouette. No sample is empty/constant. This does not
  prove all producer coordinates, comparison inputs or final shadows correct.
- The captured producer state has negative-W/positive-W clip mode, Z scale
  1 and offset 0. Existing shader conversion `(z+w)/2` expects viewport range
  -1..1, but `vk_render_viewport` clamps it to 0..1. The actual old function
  maps the controlled depth 0.2 to 0.6. Preserving the endpoints maps it back
  to 0.2 without changing clipping or shader code. A separate receiver depth
  of 0.4 demonstrates an incorrect LESS shadow result under the old mapping.
  These example coordinates are synthetic; phone receiver values are not captured.
- `tools/patch_scarletnx_zelda_depth_range.py` applies after VB_POOL and
  restores first. Runtime `SNX_VK_DEPTH_RANGE=1`, UI **Preservar faixa de
  profundidade**, ON by default only in its new profile. The actual existing
  extension enumeration must advertise `VK_EXT_depth_range_unrestricted`
  before it is enabled. OFF/unsupported/nonfinite paths retain old behavior.
  Original SPIR-V, cache keys/files, XY/origin, culling, bias, waits, copies,
  all performance ports, Stable60 and AOT remain. No new readback/submit.
- `SNX_DEPTH_RANGE_META_V1` distinguishes requested/supported/enabled.
  `SNX_DEPTH_RANGE_STATE_V1` reports up to four outside-range states;
  `SNX_DEPTH_RANGE_V1` counts viewport setups, not visible pixels or GPU time.
  The old phone log does not establish this driver extension's availability.
  If supported/enabled are zero, do not claim this repair ran on that device.
- Build `SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-profundidade-termux.sh`.
  Output `Download/ZeldaRecomp/Zelda-SNX-PROFUNDIDADE.apk`; prior buffers APK
  backed up once as `Zelda-SNX-BUFFERS-ANTES-PROFUNDIDADE.apk`. Install update,
  keep both captures OFF, LEVE, native translator and every previous option
  equal. Compare the new depth option OFF/ON in fresh processes at the same
  outdoor spot, screenshots and logs. No new shader dump is required.
- 53 host audit tests pass, zero skips with real SPIR-V validation; actual
  device-selection snippet and old/new viewport functions cover 160 vectors,
  supported/unsupported/OFF/error cases and original clipping conversion.
  Entire patch stack restores byte-exactly. Signed-APK gates, analyzer,
  ASan/UBSan, full C syntax of device/render/renderer, changed Java parsing
  and shell syntax pass. No Android APK/game or physical GPU pixels tested here.

**Resume:** inspect the new capability/state log and visual OFF/ON. If active
but shadows remain missing, compare corrected depth with consumer coordinate/
reference/bias evidence. Preserve the user-approved FPS improvement; do not
repeat FSWZADD. Interior lighting, water/color and blur remain separate pending
effects. The pagemap permission failure/content-check cost and clean performance
A/B remain established memory work below; this depth repair does not resolve them.

## Previous buffer/WW stopping point and phone evidence

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
- That first log reported three saved samples (frames 764, 1656, 2541, one
  layer each) without pixel files. The later shadow ZIP supplies those exact
  pairs and is now analyzed in `zelda-depth-range.md`. Saving depth data alone
  does not establish correct projected shadows.

The requested shadow ZIP has now been received/analyzed; see the current
viewport-depth stopping point above. Separate fresh-process pool OFF/ON logs
with both captures OFF and telemetry LEVE remain useful for performance;
no rebuild is needed just to change those options. Then compare allocation
counts with frame p95/p99. For memory work, audit a safe Android content-
verification/invalidation path under the observed pagemap denial rather than
assuming headers can activate tracking. Dynamic textures, shader coverage,
partial updates and pacing remain. Missing shadows/lights/water stay on the
independent visual track below; the latest diagnostics have not fixed them.

## Earlier visual diagnostic: depth ZIP received; viewport correction now delivered

The earlier user request prioritizes missing shadows, lights and water using
nxnative as the reference. Read [`zelda-shadow-depth.md`](zelda-shadow-depth.md)
when continuing that independent track; performance changes do not prove a
visual correction. The user subsequently authorized the buffer/WW step above.

- Existing shader captures were already analyzed; do not re-run the rejected
  FSWZADD experiment. The supplied log has shadows ON and real 2048x2048 D24S8
  2D-array shadow views. Those earlier traces showed setup/bind activity; the
  current ZIP supplies actual depth pixels, analyzed in `zelda-depth-range.md`.
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
- The requested capture ZIP has arrived, with nonconstant depth in all three
  samples. Do not request the same initial run again. First test the new
  viewport option visually OFF/ON with capture OFF; capture a later corrected
  depth session only if more consumer/producer evidence is needed.
- Host validation: 44 audit tests pass, zero skips, including the real Java
  exporter compiled for Java 8, native delayed capture/format tests and the
  byte-exact complete patch stack rollback. Real `spirv-val` remains enabled.
  Full patched `render.c`/`renderer.c` syntax and ASan/UBSan pass. LeakSanitizer
  is unavailable under this host's `/proc` restriction. No Android APK or
  device/game run was performed here.

The layer inspection and producer/consumer matching are complete for the
received ZIP. They demonstrated a viewport-depth mapping error, now covered
by a reversible capability-gated correction above. Device confirmation remains.
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

After the depth delivery the user reports colors/water resolved; photos show
partial projected shadows and blur. Atmospheric haze, indoor shafts/reflected
light, residual shadows and localized blur differences remain. Fresh logs
for the passive composition diagnostic are pending. Do not call an optimization a visual fix without
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
