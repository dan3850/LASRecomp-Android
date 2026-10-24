# Zelda: two lighting logs received; compare actual soft-effect depth pixels

Updated 2026-10-24. This delivery adds opt-in pixel evidence, **not a new
shadow/fog/light repair**. Preserve the accepted colors/water, depth-range
correction, performance ports, Stable60, AOT and caches.

## Evidence received

Private files, not committed:

| File | SHA-256 | Complete windows / elapsed time |
|---|---|---|
| `Zelda-SNX-nevoa.txt` | `732e2167fbdfa5455306cbab80135a445e67acfa6db3ae58b404362bffd9eb24` | 6 / 30.053 s |
| `Zelda-casa telefone.txt` | `49b40291930a7f7ad8494d92bdb6f236159913ea0581e1efe7968a5cb2f6cf14` | 12 / 60.107 s |

Both are revision `3d0b426db3a58d1058b4902ca4cc13529a03852f` with the native
ScarletNX translator, confirmed-completion waits, hash-span, transfer reuse,
uniform snapshots, clear loads, uniform extent, binding reuse and persistent
buffers ON. The depth correction is requested, supported and **enabled**.
All 548,672 / 362,067 observed viewport setups use its unrestricted path.
These are setup counts, not draws/pixels. The reported endpoints are -1, +1.
Shader/shadow capture is not armed. GPU detailed diagnostics are active.

Parse only the one `SNX PERF BEGIN/END` block: startup/tail excerpts repeat
some rows. The final uncompleted graphics window is useful qualitative
state evidence, but must not be included as a complete performance window.

With the first 10 seconds excluded, the existing analyzer reports:

| Named session | Remaining complete time | Renderer rate | Renderer p95 / p99 interval |
|---|---:|---:|---:|
| External haze | 20.033 s | 60.000 frames/s | 17.662 / 18.001 ms |
| Telephone house | 50.081 s | 59.404 frames/s | 18.000 / 20.095 ms |

These are measured renderer observations in **GPU detailed** sessions,
including any movement/scene transition in those windows. They do not prove
a speedup, physical Android scan-out, simulation rate or stable 60 everywhere.
There is no matched OFF/baseline run. JIT wait/compile/failure counters are
zero. Both logs load the existing Vulkan pipeline cache (4450 KB); the
`SNX_RYU_CACHE` persistent flag describes the inactive Ryujinx experiment,
not a disabled native cache. Write-watch still fails opening pagemap with
EACCES; strict content verification remains necessary.

The existing GPU timestamp profiler also identifies substantial **gaps that
contain copies** (for example, 4.93 ms/frame in the final reported outdoor
interval and 9.28 ms/frame in a reported house interval). These include
ordering/pass-boundary effects; they are not isolated copy instruction
durations, cannot be added to overlapping CPU waits as frame cost, and are
not permission to remove synchronization. Keep this as a separate performance
lead after the visual defect is established.

## What the new state records establish, and what they do not

- Complete windows contain 384 / 663 lighting state records and 360 / 636
  color-RT input records. State capacity is reached in all 6 outdoor windows
  and 5 of 12 house windows. The house has several uncapped later windows;
  bounded outdoor state evidence does not enumerate every effect.
- House records contain additive composition (`SRC_ALPHA`, `ONE`, `ADD`)
  and conventional transparency (`SRC_ALPHA`, `ONE_MINUS_SRC_ALPHA`, `ADD`).
  Alpha test is disabled in the observed fixed-function states; the shaders
  may still discard fragments themselves. Write masks and blend enum mapping
  do not show a demonstrated fault. Do not change constants/gamma/blending
  merely because the image lacks a light beam.
- In the house, shaders `86d5a3f915a6795f`, `2957c0d7d6264a3a`,
  `7444fc6ce498b4bf` read normal, noncomparison scene depth at slot 0.
  In the outdoor log `9f178ae97683fd4e` does likewise. Those reads resolve
  real 2D D24S8 views at `550d10000` / `5504a0000`, distinct from the active
  depth attachments `54da60000` / `54c980000`.
- These hashes already match the supplied private shader corpus. The short
  house programs reconstruct depth through projection parameters and a
  saturating difference contributing to alpha, then test/discard by a
  uniform threshold: consistent with soft effects. This identifies
  **candidates**, not proof which program produces a window shaft or fog.
  No repeated shader recapture or FSWZADD experiment is justified.
- The log shows real views and state preparation. It does not show sampled
  pixels, uniform values, all ordinary art texture inputs, actual visible
  fragments or the producer/age of the scene-depth copy. A valid descriptor
  can still reference stale or inappropriate contents. That is the next
  missing evidence; no resource/shader repair is established yet.

Current upstream was also checked through ScarletNX `285176ece26d4faa5c2414daabffc444ff1555ae`.
Its [non-WW change](https://github.com/scarletnx/ScarletNX/commit/d5835035ea8b1af80bb724fe7220ee478dfd4b6b)
lets settled textures use sampled checking instead of whole-epoch checks;
do not copy that as a shortcut around this task's integrity requirement.
The [alias-order correction](https://github.com/scarletnx/ScarletNX/commit/e28a03ac7bdb6d07cd12ceebb8fe6b4e9cf238ec)
is a separate correctness lead, not proof of this title's missing light.
Keep the pinned working runtime/AOT; a wholesale update also brings ABI and
shader/cache changes outside this bounded visual investigation.

## Delivered capture: one attachment and one sampled image at the same point

`tools/patch_scarletnx_zelda_effect_depth.py` applies after lighting
diagnostics, restores first. It adds `effect_depth.h` at the existing resolved
nonindexed descriptor path. Independent launcher option **Capturar profundidade
de luz/nevoa (3 pares)** defaults OFF, gated by `Zelda-EffectDepth.txt`.
It does not turn on with GPU detailed logging. Environment:
`SNX_EFFECT_DEPTH_DIR`, a fresh private capture directory per game process.

Only the four observed fragment hashes, slot 0, a real nonshadow 2D depth
view, and a distinct current depth attachment qualify. Both images must
have identical actual dimensions/format, one layer, one mip, defined layouts,
and no volume depth. Only 32-bit DEPTH-aspect copies (D24/D32 families) qualify.
Different sizes/formats and all unrelated shaders follow normal rendering.

From 15 seconds after initialization, record at most three pairs at least
15 seconds apart. A pair has one dedicated mapped buffer, **64 MiB maximum
combined logical bytes**, also within the device allocation cap. Only one
buffer is pending. Allocation failures have bounded retries; no refused
diagnostic skips a draw. The actual buffers are released after retirement.

Both image-to-buffer copies are recorded at the same descriptor-preparation
point, before the candidate draw. Existing `vk_surf_use` orders them, and
restores each image's exact original layout/stage/access. One COPY-write to
HOST-read dependency precedes the existing frame-retirement callback; only
then does the CPU invalidate/read/save. No new explicit submit, timeline
wait, device idle, guest write, texture replacement or shader change.
There are up to three extra pass breaks, readback traffic and disk writes:
capture ON is unsuitable for FPS comparisons. OFF does no image inspection.

Each `effect-1..3.depth` contains two tightly packed planes: attachment first,
sampled image second. Matching `.json` is published last and records explicit
offsets/bytes, both addresses/generations/guest sizes, actual dimensions,
consumer hash/slot/TIC/TSC and current viewport/depth state. D24 is Vulkan
X8_D24_UNORM_PACK32, with undefined high byte, not guest packed stencil.

The attachment is a **comparison candidate**. Metadata explicitly says
`producer_relationship: unproven`. An earlier copy followed by legitimate
depth writes can differ from the current attachment. A difference alone is
not a proven copy bug. There is no synthetic producer attribution.

`ShadowCaptureExport.writeEffects` reuses the bounded newest-session export
with a separate directory/prefix. It never picks older successful captures
if the newest is empty. Old shadow export keeps its existing behavior.
The effects ZIP contains only complete matching pairs and the runtime log.
The FPS analyzer rejects an armed effects-capture session.

## Incremental phone test

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-efeitos-termux.sh
```

APK: `Download/ZeldaRecomp/Zelda-SNX-EFEITOS-DEPTH-DIAG.apk`.
The prior lighting APK is saved once as
`Zelda-SNX-ILUMINACAO-ANTES-EFEITOS.apk`. All existing builders/caches/AOT are
reused; no full game recompile, cache deletion or stable-branch change.

1. Install as an update. Keep **Preservar faixa de profundidade ON**, previous
   performance options and Stable60 ON, live Ryujinx OFF.
2. Capturar shaders OFF, Capturar sombras OFF, **Capturar profundidade de
   luz/nevoa ON**, Registrar FPS **LEVE**. Start a fresh game process.
3. Enter the telephone house promptly, stay there about **60 seconds**, exit
   normally and use **Exportar profundidade de luz/nevoa (.zip)**. Save
   `Zelda-efeitos-casa.zip`. The existing two scene logs need not be repeated.
4. In another fresh process, repeat outside at the haze comparison spot and
   save `Zelda-efeitos-nevoa.zip` if ready to collect both scenes.
5. Turn the new capture OFF and restart for normal play. Keep the depth
   correction ON. Observe any visual change during capture, since the
   diagnostic's pass boundaries can influence ordering defects.

Offline analysis, no extra packages:

```bash
python tools/analyze_zelda_effect_depth.py /storage/emulated/0/Download/Zelda-efeitos-casa.zip
```

The analyzer checks bounded shape/format/offsets/byte counts, one session,
at most three complete pairs and duplicate ZIP entries. It masks undefined
D24 bits, reports each plane's depths and finite-pair differences, and can
write orientation-preserving `--previews <directory>` PGM files. It never
declares a difference to be a bug.

## Host validation and stopping point

61 host audit tests pass, zero skips with real spirv-val. The new native
fixture executes the actual pinned `vk_surf_use`: OFF/early/unrelated/invalid
images do no work, source states and input bytes are unchanged, two copies
have exact nonoverlapping offsets, invalidation/read happens only after
normal retirement, failed allocations/maps/files remain bounded, queued
metadata owns its words, and all three captures retire without leaks.
D24 undefined bits, float depths, malformed/absent ZIP pairs, profile gates,
FPS-session refusal and full-stack apply-twice/exact rollback are covered.
Actual Java exporter tests retain old shadow behavior and isolate effects.
New fixture ASan/UBSan and full patched render/renderer C syntax checks pass.
Changed Android Java parses; Android type/link/package validation remains
for the user's incremental Termux build. No new Android/APK/GPU pixel result
or FPS gain is claimed from host checks.

Resume with the paired pixels. If sampled depth is plausible, inspect the
candidate shader's projection/uniform/art-texture inputs and color output.
If images differ unexpectedly, trace their actual blit/copy lineage before
changing lifetime/barriers. Remaining visual work: outdoor haze, indoor
shafts/reflected light, residual shadows and local blur differences. Preserve
the user-accepted colors/water. Performance work on copy gaps and permitted
write tracking remains separate, with equal-route LEVE A/B tests pending.
