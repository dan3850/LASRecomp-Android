# Link's Awakening Android: FPS audit and controlled experiments

Baseline: `29a6f237d20ba9f960a4daa8e1ae9a25309ecc43` on
`experimental/zelda-links-awakening-ryujinx-nativeaot`.
ScarletNX is pinned to `34853eeae5af132e320adbb0193f13344085bf89`.
Game: `01006BB00C6F0000`, 1.1.0, main Build ID
`909E904AF78AC1B8DEEFE97AB2CCDB51968F0EC7`, Android ARM64.

## Scope and evidence

This is a source audit and a reproducible measurement build, not a measured
FPS claim. No Zelda executable, NSP/XCI, RedMagic, Android Vulkan driver or
Android SDK/NDK is available on the audit host. Host C regressions execute
telemetry and mocked synchronization/cache behavior; they cannot validate
Adreno rendering, audio, animation speed or achieved FPS. The Termux build
reuses the user's separately generated Stable60 AOT and existing native build
caches. No stable branch, guest instruction, AOT ABI or mod site is changed.

The requested `src/nx/gpu/vk` files belong to ScarletNX, not this repository.
The effective Android source is that pinned checkout plus the reversible
patches in the Termux scripts. Changes are delivered as guarded patches here.

### Important wiring issue

At the baseline, `CastlevaniaSnxBootActivity` passes the Ryujinx choice to
`MarioSnxGameActivity`, but the latter enables `SNX_RYUJINX_NATIVE_PROBE` only
for **Castlevania** (`0100BA4026E94000`). It does not enable it for Zelda.
Packaging `libRyujinxShaderNative.so` is not proof of using it.

The standard Zelda build selects the **v1** live adapter. ABI 2 is a separate,
optional path selected by `SCARLETNX_RYU_V2=1`; it is not the standard Zelda
build. The v1 patch bypasses the translated-shader file in `pf_start_load`,
but originally leaves the driver pipeline cache enabled. The optional v2
patch bypasses both and also has extra per-shader live GPU facts, which the
original `PfShader` format cannot serialize.

The launcher now recognizes the Zelda title for explicit live translation.
A fresh preference, default OFF, prevents an old ineffective selection from
silently changing the working renderer. Keep Ryujinx OFF for the first baseline.
An active translation must have the adapter-ready and shader-selected log
lines; `ryujinx_requested` in metadata alone proves only the request.

## Existing optimizations: do not implement them again

| Files / path | Already present | Consequence |
|---|---|---|
| `cmd.c` | Two frames in flight; timeline per submission; persistent staging/readback rings; deferred destruction; reused descriptor pools and batched set allocation | Increasing buffering or destroying/resetting on each submission is not an initial fix. |
| `release.c` | A release thread; deferred CPU-visible releases; monotonic prefix gates; release payload forwarding; GPU occlusion predicates | Do not remove gates or force every release to submit. |
| `renderer.c` | WAIT_FOR_IDLE represented by a GPU barrier; nonblocking swapchain acquire; offscreen submissions still advance the ring | A missing swapchain image is not a completed displayed frame. Ordinary guest WAIT_FOR_IDLE does not call `vkDeviceWaitIdle`. |
| `pipeline.c` | In-memory shader cache with CB reads; background pipeline workers; deferred pipeline resolution on recording thread; pipeline cache feedback | Async pipeline creation already exists and still waits before the draw uses the required pipeline. |
| `pipeline_file.c` | Checked append-only SPIR-V/ShaderInfo/CB-read records; references from pipeline records; bounded file; partial-record recovery | Reuse this implementation; retain checks, source keys and bounds. |
| `texture.c` | Upload validity/retry; content hashes and write generations; render-target views; feedback copies refreshed by generation; staged conversion; ASTC GPU path | Skipping uploads or comparing only a few texels would break correctness. |
| `surface.c` | Target reuse, LRU/budget trimming, read-after-read barrier suppression, explicit access tracking and readback visibility | Broadly deleting barriers or readback invalidation is unsafe. |
| `memory.c` | Allocation caps, budget accounting, sparse large-image allocations | Sparse-bind fence waits establish actual binding completion; not a demonstrated per-frame bottleneck. |
| `buffer.c` | Small draw data in rings, immutable cached buffers, write-page generations, GPU-owned results and composed copies | Much of the GPU-to-CPU-to-GPU avoidance already exists. Capability fallback matters on Android. |
| `record.c` | A recording thread, command ring, allocation/write batching, counters of transfers/barriers | `vk_rec_sync` waits for CPU recording/submission, not GPU execution. Measure separately. |
| `gpuprof.c` | GPU timestamps per rendering pass, gaps by copies/dispatches/barriers, most expensive targets | Use its detailed mode before changing shadows, render passes or target formats. |
| `guest_jit.c` / `present.c` | AOT dispatch, on-demand JIT with persistent units/warm hints, guest pacing outside GPU thread | 434 AOT blocks do not prove zero JIT misses. Preserve the limiter and mod together. |

## Ranked hypotheses, not unmeasured conclusions

| Priority | Candidate / source evidence | Expected impact if confirmed | Risk | Difficulty | Evidence required |
|---|---|---|---|---|---|
| 1 | Shader translation/pipeline creation on scene entry; v1 persistent prewarm bypass | High on repeated stutter; may not change steady-state FPS | Medium for isolated v1 persistence; high for v2 serialization | Medium / high | Backend selected; shader/pipe counts and ms fall on second identical route without new skipped draws. |
| 2 | Graphics timeline and CPU-visible result landing (`buffer.c`, `release.c`, frame recycle) | Potentially high when serialized; already-completed host waits likely a smaller gain | Low for reusing confirmed completion; high for changing landing semantics | Low / high | Timeline/recycle/finish wall time, release/writeback reasons, GPU pass/gap time. |
| 3 | CPU texture hashing when written-page tracking is unavailable; eager landing when memory traps are unavailable | Potentially high on affected Android kernels | High for a new tracking/ownership backend | High | `no write tracking`, `no traps`, texture_hash time/bytes and writeback/finish costs. |
| 4 | Actual Adreno pass cost: targets, shadows, feedback passes/copies | High sustained-FPS potential if GPU bound | High for rendering changes | High | `gpuprof` pass/target ranking; scale, formats, copied MB/frame and gaps. |
| 5 | CPU recording/driver submission/descriptor churn | Medium if the GPU is starved | Medium | Medium | Recording drain time vs driver API time, sets reused/written, GPU empty gaps. |
| 6 | Missed AOT code, JIT compilation and waits | Unknown; high only if actually encountered in gameplay | Medium / high | Medium / high | JIT batch compile and miss wait counts/ms in the measured route. |
| 7 | Presentation pressure, refresh and guest swap interval | High for perceived consistency when mismatched | Medium | Medium | Guest/render/enqueue rate, no-image counts, pacing time, Android presentation trace. |

The graphics timeline includes results the guest CPU can read. Removing a
wait because it is expensive is not a valid optimization. `surface.c` host
barriers, noncoherent allocation invalidation and alias/writeback rules remain.

## Measurement build

```bash
cd "$HOME/LASRecomp-Android"
git status --short
git fetch origin experimental/zelda-links-awakening-ryujinx-nativeaot
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git merge --ff-only origin/experimental/zelda-links-awakening-ryujinx-nativeaot
export SCARLETNX_BUILD_JOBS=2
bash ./compilar-zelda-fps-audit-termux.sh
```

If there are local edits, preserve them before updating. No reset, clean or
cache deletion is part of this procedure. The script checks the existing
Stable60 AOT symbol and uses
`/storage/emulated/0/Download/ZeldaRecomp/Stable60AOT/01006BB00C6F0000_code.so`
by default. An existing `ZELDA_SNX_CODE_SO` override is respected. It does not
invoke `scarletnx -r` or build game LLVM blocks.

The current audit APK enables the operand-exact FSWZADD repair described below
and uses `shader_cache/fps-audit-fswz-v1/`. The comparison build with
`SCARLETNX_ZELDA_FSWZADD=0` uses the earlier `shader_cache/fps-audit-v1/`.
The working APK's existing
shader and driver files are not opened or overwritten. Its first run therefore
warms a separate audit cache. Compare A/B in this same audit binary after
warming the native cache, rather than comparing a cold audit APK with a warm
older APK. Gradle/CMake/Ninja/LLVM/dependency caches and the game AOT are reused.

APK: `/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-STABLE60-FPS-AUDIT.apk`.
The previous toggle APK is copied once to
`Zelda-SNX-STABLE60-ANTES-FPS-AUDIT.apk` before the build. Same package: install
as an update and keep app data/saves. Use a new process for every trial.

Choose **Registrar FPS no log: LEVE** in the launcher. This records evidence
in the exported log; it is not an on-screen FPS overlay. The default is OFF. Keep
shader capture OFF and use the same Home > Stable 60 FPS setting each time.
Use the same save, route, camera, resolution, vsync, display refresh, cooling,
performance mode and power state. Avoid recording the screen during trials.
Warm up, then repeat a 90-second route at least three times, exporting each
run through **Salvar log** before the next run. Exclude menus/loading from
the selected time range. `--skip-seconds` refers to time since renderer start,
not time since entering the save.

Detailed GPU mode additionally enables the existing
`SNX_VK_GPU_PROFILE=1` and `SNX_VK_BUFFER_STATS=1`. It adds timestamps per pass
and buffer bookkeeping, plus the bounded graphics evidence described below.
Use it to locate the expensive work; compare A/B FPS
using LEVE in both runs. Profiling OFF is also available for overhead checks.

Every five seconds the log includes bounded raw frame intervals, window
counts, shader/pipe/upload/descriptor/copy/barrier deltas, CPU texture hash and
upload times, graphics timeline waits, frame recycling, recording drain,
driver submit/present, acquire misses, guest pacing and JIT costs. Logging
happens outside the telemetry lock. The exporter retains telemetry once in a
dedicated bounded section; truncation and missing chunks are rejected by the
analyzer. The last incomplete five-second window is intentionally excluded.

```bash
cd "$HOME/LASRecomp-Android"
python3 tools/analyze_zelda_perf.py "/storage/emulated/0/Download/Zelda-A.txt" --skip-seconds 20
python3 tools/analyze_zelda_perf.py "/storage/emulated/0/Download/Zelda-A.txt" \
  --compare "/storage/emulated/0/Download/Zelda-B.txt" --skip-seconds 20 --seconds 60
```

It reports nearest-rank pooled p50/p95/p99 from actual microsecond samples,
not an average of per-window percentiles. Multiple concatenated sessions
require `--session N`. Counters are per selected window; parallel thread
times overlap and must not be summed as a frame-time budget. `hash_bytes` has
bytes as its count, rather than calls. GPU timestamps are GPU measurements;
CPU submission API time is not GPU execution time.
`show_wall` measures wall time inside the final renderer `show()` path,
including its waits; it is not GPU-thread CPU utilization or total frame CPU
time. A short final partial window is not extrapolated.

## First RedMagic measurement and visual comparison

The supplied `Zelda-SNX-boot (4).txt`, revision `9f9ea9a`, contains a valid
LEVE session with live Ryujinx, confirmed waits and Ryujinx persistence OFF.
For the ten complete windows inside elapsed 20 to 80 seconds, the available
data actually covers 50.103 seconds (approximately 20.044 to 70.147):

| Evidence | Observed |
|---|---:|
| Renderer / successful presentation enqueue cadence | 51.494 frames/s |
| Renderer interval p50 / p95 / p99 | 18.842 / 21.036 / 23.109 ms |
| Longest renderer interval | 189.316 ms |
| Skipped draws | 0 |
| Texture content hashing | 9,202.161 ms over 454,734 checks; 119,167,188,992 bytes |
| Graphics timeline host waits | 26,519.477 ms over 10,324 calls |
| New graphics pipelines / cumulative pipeline wait | 24 / 820 ms |
| New shaders / translation time | 18 / 7 ms |
| JIT compilation / guest miss wait | One batch, about 62.4 ms |

These overlapping thread costs are not a frame-time decomposition or a
prediction of recoverable FPS. Texture hashing alone averages about 3.57 ms
per renderer frame. The runtime reports `no write tracking`, while GPU-owned
guest-memory trapping is active. Native persistence already works: 160
shaders and 200 earlier pipelines load, with all 200 prewarmed from the driver
cache. New pipelines still stall scene entry; a 189 ms frame includes 169 ms
of pipeline waiting. The log does not identify which GPU passes consume the
timeline wait. Physical display rate and simulation speed remain unmeasured.

The user's three Eden reference captures and corresponding LASRecomp captures
show projected ground shadows missing, interior light shafts missing or
greatly reduced, and a visibly different water appearance. Leaf highlights,
geometry and some water highlights remain. This is visual evidence of partial
rendering differences, not proof that every missing effect shares one cause.
The static FPS overlays in the pictures are not a controlled performance
comparison. No shader or synchronization semantic is changed on that basis.

### Detailed graphics evidence for missing effects

The current native `render.c` can bind `vk_null_view` when a texture/view
cannot be used, then continue the draw. Thus zero skipped draws does not
exclude missing shadow or lighting resources. Some null descriptors, notably
unused indexed elements, are intentional and are not errors by themselves.

Selecting **Registrar FPS no log: GPU DETALHADA** now also sets
`SNX_GFX_DIAG=1` in the fresh Zelda child process. LEVE and OFF do not enable
this resource trace. It logs:

- `SNX_GFX_META_V1`: the effective native shadows setting and detail limits.
- `SNX_GFX_PASS_V1`: draw setup signatures with vertex/fragment shader hashes,
  color/depth target addresses, dimensions, Vulkan formats and depth state.
- `SNX_GFX_BIND_V1`: relevant texture preparation decisions, shader/slot,
  handle, requested view/numeric kind, candidate surface and format,
  depth/manual comparison state and selected TIC/TSC words. Null, depth,
  shadow and non-2D resources receive detail; ordinary valid 2D color binds
  only increment counters. Handle zero is treated as a valid handle.
- `SNX_GFX_V1`: per-window draw setup and binding counts, including depth-only
  setups, null/shadow bindings, indexed entries and shadow samplers with an
  unexpected color view. The analyzer includes these under `graphics`.

Signatures are exact and deduplicated, bounded to 64 draw setups and 128
bindings per five-second telemetry window. `SNX_GFX_LIMIT_V1` reports a reached
limit; counters continue and the next window gets a fresh detail budget.
The normal bounded exporter retains these records and detects truncation.
These are CPU setup events: a depth setup does not prove nonempty shadow-map
pixels, and an indexed entry does not prove it was sampled dynamically.
The trace never retries a resource, reads texture pixels, changes a
descriptor, submits work, adds GPU waits or changes shader/cache decisions.
Its CPU/logging overhead makes it diagnostic evidence, not the mode for an
A/B throughput claim.

For the next visual trial, install the current audit APK as an update, fully
end the game process, select GPU DETALHADA and leave Ryujinx, confirmed waits,
Ryujinx persistence and shader capture OFF. Keep the previous Stable60 setting.
Visit the same outdoor trees, telephone-house interior and water scene for
about 20 seconds each, then export the log before starting another run.
No AOT regeneration or cache deletion is required. This stage instruments the
failure; it does not claim that shadows or lighting have been corrected.

### Detailed RedMagic result: resources are bound, pixel correctness unresolved

`Zelda-SNX-boot (6).txt` confirms detailed mode on `02f1f3c`, with
`shadows_enabled=1` and the native translator. The twelve complete windows
after elapsed 20 seconds cover 60.144 seconds and 3,150 renderer events:

| Evidence | Observed |
|---|---:|
| Renderer / presentation enqueue rate | 52.374 / 52.357 frames/s |
| Renderer p50 / p95 / p99 | 18.594 / 25.837 / 34.196 ms |
| Depth-only draw setups | 473,973 |
| Texture binding events / null bindings | 2,539,221 / 0 |
| Shadow binding events / null shadow bindings | 237,514 / 0 |
| Shadow samplers with unexpected color views | 0 |
| Skipped draws | 0 |
| Texture content hashing | 8,964.322 ms; about 2.85 ms per renderer event |
| Graphics host timeline wait | 30,215.390 ms |
| JIT compilation / guest miss waits in this interval | 0 / 0 |

Detailed mode and a different scene mix mean these FPS figures are not an
A/B gain claim. The counters rule out an explicit shadows-OFF setting and
null-view substitution for the measured bindings; they do not establish the
contents of a shadow map or the results of a shader comparison.

All recorded shadow sampler signatures reference address `5432b0000`,
2048x2048, Vulkan format 129 (D24_UNORM_S8_UINT), requested as a 2D array.
The same address appears in depth-only setups with depth test/write enabled
and also in the GPU's timed target list. This correlates a produced target
with its consuming shader bindings. Layer contents, coordinates, references,
shader semantics and the driver's rendering still need examination. The
trace has no GPU pixel readback and cannot prove that the map contains the
expected occluders. Its detail limits are reached in some windows; the
untruncated per-window counters continue regardless.

During gameplay the existing profiler records roughly 2--5 ms per frame in
passes and roughly 7--9 ms in gaps containing copies. These timestamps include
the interval between passes: pipeline bubbles, CPU submission delays and
semaphore waits can be included. They are not isolated measurements of a
particular transfer's execution time. Texture hashing, staged copies and
dependencies between passes are stronger next performance targets than JIT
in this specific run. No wait or correctness check is removed on that basis.

### Complete shader capture without deleting a warm cache

The next required evidence is the actual shader programs for the identified
depth map and its readers. The previous launcher enabled `--diag=1` but the
native prewarm guard only checked `SNX_SHADER_CORPUS`. With an existing warm
shader file, previously translated shaders could therefore escape capture.
The old ZIP export also included fragment stage 4 only, omitting vertices
needed to examine shadow-map generation.

In the audit patch, `pf_start_load` now also checks
`g_settings.shader_captures`. For a capture session it does not prewarm or
append translated-shader records and logs `SNX_SHADER_CAPTURE_V1`; existing
files remain in place. Turning capture OFF restores the original persistent
shader policy. The driver pipeline cache is retained under the normal native
policy. The original `shader_corpus_save` records each newly encountered
in-memory shader; no alternative shader, partial shader or placeholder draw
is introduced.

The launcher's **Exportar shaders de todos os estagios (.zip)** includes the
existing private `.snxs` captures for stages 0--5: vertex, tessellation control,
tessellation evaluation, geometry, fragment and compute. File-name, file-size
and file-count bounds are retained; the ZIP still contains only files under
`captures/shaders`, not the game container, keys, saves or AOT module. Earlier
captures are retained as well, so ZIP presence is not proof of current use;
the detailed log's shader hashes and state identify the relevant programs.

After updating this audit build, fully end the child, select GPU DETALHADA,
enable **Capturar shaders na proxima execucao**, leave Ryujinx, confirmed waits
and Ryujinx persistence OFF, and keep Stable60 at the prior setting. Visit
the three comparison scenes briefly, then export the shader ZIP and log
before another launch. Capture adds translation and I/O overhead; it is for
correctness diagnosis, not a performance comparison. Disable it afterward.
No full AOT rebuild or cache deletion is needed.

## Captured-shader finding and operand-exact FSWZADD repair

The supplied `Zelda-shaders-SNXS.zip` contains 155 complete version-1 programs:
70 vertex, 81 fragment and 4 compute. Its SHA-256 is
`c4b28370299c2359d542c96194bf48476a291e0f397e24d84767bc2cc3f8a6f8`.
Each header has the pinned 2,096-byte ShaderInfo. Captures are private audit
inputs and are not committed; tests contain synthetic Maxwell programs only.

| Offline check | Original translation | Repaired translation |
|---|---:|---:|
| Programs translated | 155 | 155 |
| Unsupported / SPIR-V validation failures | 0 / 0 | 0 / 0 |
| SPIR-V modules changed | — | 28 fragment programs |
| Modules byte-identical to original | — | 127, including all vertex/compute programs |

Validation used the real SPIRV-Tools `spirv-val --target-env vulkan1.3`.
Structural validity did not catch the following arithmetic error.

All 28 captured fragment programs that contain a depth-compare TEX also use
FSWZADD: one A5 and one 99 per program (56 instructions). Their SrcA values
come from SHFL.BFLY of SrcB across the corresponding axis. In the pinned
translator, those FSWZADD forms unconditionally become `dFdx(SrcB)` or
`dFdy(SrcB)`, ignoring SrcA. This is not their defined operation. The sign
table in Ryujinx's `InstEmitWarp.Fswzadd`, GLSL `SwizzleAdd.glsl`, and SPIR-V
`GenerateSwizzleAdd` selects x+y, y-x, x-y or y for selectors 0,1,2,3.
For the captured A5/99 shuffle pairs, the previous derivative has the opposite
sign; for unrelated operands, substituting a derivative is invalid altogether.

`tools/patch_scarletnx_zelda_fswz.py` repairs the four already accepted masks
(99,66,A5,5A), using both actual operands and the same subgroup lane numbering
as the existing SHFL implementation. It does not add accepted forms or alter
the older D7 experiment. It requests the existing subgroup capability before
using the lane builtin, with the existing explicit refusal if unavailable.
All 155 captured programs still translate. No draw, resource check, barrier,
wait, guest timing, Stable60 code or AOT block is removed or changed.

The host regression compiles the actual pinned shader translator before and
after the repair. With SrcA=13.25 and SrcB=-7.5, mask 99 previously emitted
zero in every lane; the repaired program produces -20.75,+20.75,-20.75,+20.75.
Tests execute the emitted straight-line SPIR-V through the fragment output
for all four masks, both independent operands and SHFL pairs, at four lane
group bases. The small test evaluator rejects unhandled instructions and is
not a general GPU emulator. All eight synthetic modules also pass spirv-val
when available. This proves the arithmetic regression, not game pixels/FPS.

The shader and driver files for repaired translation use the separate
`shader_cache/fps-audit-fswz-v1/` directory. Earlier directories are preserved
and cannot prewarm stale SPIR-V into the repaired runtime. The patch/cache
change is transactional and restored first when leaving the shared build;
the complete real-source stack is checked for byte-exact rollback. The signed
APK check requires `SNX_FSWZADD_V1` exactly when the repair is requested.

### Termux build and visual verification

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 SCARLETNX_ZELDA_FSWZADD=1 bash ./compilar-zelda-fps-audit-termux.sh
```

Install `Zelda-SNX-STABLE60-FPS-AUDIT.apk` as an update. The builder preserves
the previous toggle APK once as `Zelda-SNX-STABLE60-ANTES-FSWZADD.apk` when
present. It reuses the game AOT and build caches. Host audit result: 13 Zelda
performance tests passed, plus the three existing D7 patch tests; no skips.
The upstream shader regression passes with this repair on its original
translator and its 68 emitted modules pass spirv-val. With the pre-existing
bindless diagnostic patch included, one upstream assertion checks the old
exact error string and fails identically before/after this repair; the shader
is still refused. That configuration is not reported as an all-pass run.
Shell syntax, patch reversal and whitespace checks also pass. No Android APK
or live Zelda run was produced on this host.

For the phone trial, fully end the game process, select LEVE and leave shader
capture, live Ryujinx, confirmed waits and Ryujinx persistence OFF. Keep the
Stable60 setting unchanged. Warm the new cache on the same three scenes,
restart the game process, then record the same route for 90 seconds. Export
the log (look for `SNX_FSWZADD_V1`) and compare ground shadows, telephone-house
light shafts and the water against the earlier pictures. Screenshot capture
should be outside the measured interval. Do not compare a cold first run
against a warm earlier binary. A negative visual result remains useful: it
would leave the proven arithmetic fix separate from unresolved depth contents,
render-target/layer state and other lighting/water issues.

To compare the earlier arithmetic without deleting anything:

```bash
SCARLETNX_BUILD_JOBS=2 SCARLETNX_ZELDA_FSWZADD=0 bash ./compilar-zelda-fps-audit-termux.sh
```

That is another incremental runtime build; it uses the earlier audit cache
namespace. Alternatively reinstall the preserved pre-repair APK as an update.
The repair's visual benefit, possible shader cost and any FPS difference
remain unmeasured until matching device runs are supplied. Correctness takes
priority over throughput with missing effects.

Termux test portability follow-up: Bionic headers expose the POSIX `O_SYNC`
file-open macro before the generated Maxwell enum, which also names its SYNC
opcode `O_SYNC`. The standalone semantic test now includes `fcntl.h` and
undefines that macro immediately before the enum in its disposable header
copy. The cached ScarletNX source, generated opcode values and packaged
runtime are unchanged. A regression reproduces the failing include order,
then compiles and executes the real decoder to verify that Maxwell SYNC and
its control-stack classification remain intact. All 14 audit tests pass on
the host, including before/after shader semantics; no assertion is skipped.

## Implemented experiments (default OFF)

### Confirmed graphics completion

**Reutilizar esperas confirmadas** sets `SNX_VK_KNOWN_COMPLETE=1` for the next
child process. A monotonic atomic lower bound is advanced only after
`vkWaitSemaphores` actually returns `VK_SUCCESS` for the existing graphics
timeline. Another call for that value or an older one can return without
repeating the driver wait. A higher/unconfirmed value still executes the
original infinite wait. Error results never publish a completion, and the
watermark is reset at timeline initialization. It does not speculate from a
submission number or add a driver polling call.

Only repeated host waits are elided. The original `land_through`, compute
gates, release ordering, frame/hold values, HOST barriers and noncoherent
allocation invalidation remain. Cross-thread publication uses release/acquire
atomics. The `wait_elided` counter verifies the path is being exercised; FPS
and p95/p99 determine whether it matters on this phone. No skipped draw is
introduced by this experiment.

Reference: [Vulkan synchronization](https://docs.vulkan.org/spec/latest/chapters/synchronization.html)
and [timeline semaphore sample](https://docs.vulkan.org/samples/latest/samples/extensions/timeline_semaphore/README.html).
Timeline values are monotonic; host waiting is separate from the barriers and
cache operations that make memory visible. This implementation conservatively
reuses successful host waits rather than replacing visibility operations.

### Isolated ABI 1 persistence

**Cache Ryujinx entre execucoes** sets `SNX_RYU_PERSIST=1`. It acts only when
the live v1 Ryujinx backend was explicitly enabled. The real adapter is still
checked by `snx_rn_init`; `dladdr` identifies the actual loaded translator and
runtime files. Their bytes are fingerprinted once, with the GPU/driver/UUID,
to construct isolated shader and driver filenames. A changed runtime,
translator or driver selects a different namespace. The usual shader-file
build/features/layout key and record checks are additionally retained.

The original checked `PfShader` representation is sufficient for v1: it
contains ShaderInfo, all keyed masks, shader source hashes, CB reads and the
validated SPIR-V. This reuses the existing loader/prewarm/pipeline workers.
It neither adds a replacement shader nor drops a draw while compilation is
pending. Original capability/descriptor checks and fallback translation stay.

ABI 2 is refused because its `ryujinx` flag and live `ryu_facts` are not
serialized by that format. Capture mode disables v1 persistence; identity
failure or an overlong path disables it as well. With live v1 but persistence
OFF, both shader and driver persistence are bypassed, without touching the
old native files. With the native ScarletNX backend, its original policy
continues within the separate audit folder.

`SNX_RYU_CACHE_V1` reports the effective policy and namespace. A request in
`SNX_PERF_META_V1` is not proof that persistence succeeded. On the second
identical run, look for earlier-run shaders/pipelines being loaded, lower
translation/compile/wait time, and equivalent graphics. This primarily targets
repeated scene-entry stalls, not a claim of higher sustained GPU throughput.

### Comparisons

Keep LEVE measurement and Home > Stable 60 FPS unchanged throughout. Change
one setting between trials and start a fresh game process each time.

| Trial | Ryujinx live | Confirmed waits | Ryujinx persistence | Purpose |
|---|---|---|---|---|
| A | OFF | OFF | OFF | Functional native baseline; warm its separate audit cache first. |
| B | OFF | ON | OFF | Compare repeated graphics waits with A on the same native backend. |
| C | ON | OFF | OFF | Explicitly validate the live adapter's graphics and gameplay first. |
| D1 | ON | OFF | ON | Populate the isolated v1 cache on the same route as C. |
| D2/D3 | ON | OFF | ON | Reopen; compare warm persistent v1 with C, not with native A. |

Do not attribute an A-to-D difference to cache: those trials also change the
translator. If live Ryujinx has a graphical regression, leave it OFF and keep
using A/B; there is no need to sacrifice graphics for its cache experiment.
Any new skipped draw, rendering/pipeline error, crash, audio fault or abnormal
animation speed invalidates that trial even if its FPS counter is higher.

Both experiments can be turned OFF for the next launch. To return completely
to the pre-audit APK, reinstall `Zelda-SNX-STABLE60-ANTES-FPS-AUDIT.apk` as an
update without uninstalling or deleting data. That APK ignores the new audit
cache folder and preferences. The two development commits are also separate
so the experiment patch can be reverted while retaining measurement tools.

## Host verification

The suite `python3 -m unittest discover -s tests -p 'test_zelda_perf*.py'`
compiles and executes the real telemetry/helper headers and injected wait and
cache guards with a host C compiler. It tests multiple CPU writers, failed
waits, monotonic publication, opt-out, identity/driver changes, cold/reopened
policies, capture/identity failure, long paths, untouched legacy files, pooled
frame percentiles, missing/truncated data and transactional patch reversal.

When `SCARLETNX_TEST_SRC` names a checkout containing the pinned objects, it
also applies/reverses the complete patch stack on temporary copies of the
actual source, and compiles/runs the original `pipeline_file` regression with
its real PfShader/ShaderInfo. Its **74 checks** cover reopen, payload integrity,
missing modules, partial/corrupt records and file bounds. Only unused Vulkan
API headers are excluded from that standalone file test. No Vulkan driver or
Android rendering is exercised by it. Zelda font, Stable60 toggle, ABI-12 and
ABI-2 cache regressions are run separately; the audit APK script also verifies
the runtime markers and revision in the signed archive.

Audit-host result on 2026-10-23: **29 selected tests passed**, including the
upstream cache test's 74 internal checks; shell syntax and patch/whitespace
checks passed. No test was skipped in that run. The signed Android archive
verification is installed for the Termux build; an actual new APK, game run,
visual/audio comparison and FPS result have **not** been produced on this
host. The signed-APK unit regression uses synthetic payloads, not a game APK.

Termux portability follow-up: the original cache test assumed that opening and
writing `/dev/full` produces ENOSPC. The phone reported a failure at that
environment-dependent assertion. The standalone test now links a test-only
I/O fixture that substitutes a temporary stream for that path and injects
ENOSPC separately at a short write and at a buffered flush. All 74 original
assertions remain and run in both cases; the Python driver also requires proof
that the intended failure was injected. No assertion is skipped, and the
fixture is not linked into the Android runtime/APK. Real cache files and the
cached ScarletNX source are untouched.

### FPS definitions

* **guest_queue**: successful QueueBuffer transactions for the visible guest
  layer, before its GPU fences have completed. This is the game's output
  cadence, not a measurement of animation/simulation updates.
* **render**: completed renderer `show(..., game=1)` calls, including a frame
  that submits offscreen. It is not a count of unique images or GPU completion.
* **present_enqueue**: successful/suboptimal `vkQueuePresentKHR` calls for
  game frames. It proves submission to the Android presentation chain, not
  scanout by SurfaceFlinger. Frames unavailable at acquire are counted separately.
* **displayed/simulation FPS**: unavailable here. Actual display cadence needs
  an Android/SurfaceFlinger/FrameTimeline trace; simulation speed needs game
  timing evidence, not another rate counter. No invented 60-FPS claim follows
  from successful present calls.

## Higher-impact follow-up

The most substantial architecture-preserving candidate is making written-page
tracking and GPU ownership work efficiently with the actual Android kernel
capabilities, **if** the log reports those paths unavailable and shows large
hash/readback costs. The pinned platform code uses userfaultfd/PAGEMAP_SCAN
and minor shared-memory faults, whose availability is not implied by ARM64
or by the Adreno model. First measure the fallback cost. Any Android-specific
replacement must preserve byte-level CPU/GPU visibility, aliases, mapping
changes and guest writes; it must not merely suppress content checks. This is
a separate high-risk stage after the reversible low-risk experiments.
