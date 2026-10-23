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

This audit APK uses `shader_cache/fps-audit-v1/`. The working APK's existing
shader and driver files are not opened or overwritten. Its first run therefore
warms a separate audit cache. Compare A/B in this same audit binary after
warming the native cache, rather than comparing a cold audit APK with a warm
older APK. Gradle/CMake/Ninja/LLVM/dependency caches and the game AOT are reused.

APK: `/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-STABLE60-FPS-AUDIT.apk`.
The previous toggle APK is copied once to
`Zelda-SNX-STABLE60-ANTES-FPS-AUDIT.apk` before the build. Same package: install
as an update and keep app data/saves. Use a new process for every trial.

Choose **Medicao de FPS: LEVE** in the launcher. The default is OFF. Keep
shader capture OFF and use the same Home > Stable 60 FPS setting each time.
Use the same save, route, camera, resolution, vsync, display refresh, cooling,
performance mode and power state. Avoid recording the screen during trials.
Warm up, then repeat a 90-second route at least three times, exporting each
run through **Salvar log** before the next run. Exclude menus/loading from
the selected time range. `--skip-seconds` refers to time since renderer start,
not time since entering the save.

Detailed GPU mode additionally enables the existing
`SNX_VK_GPU_PROFILE=1` and `SNX_VK_BUFFER_STATS=1`. It adds timestamps per pass
and buffer bookkeeping. Use it to locate the expensive work; compare A/B FPS
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
