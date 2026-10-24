# Zelda: first visual-correctness stage

The current task is missing projected shadows, interior lighting and water
appearance. Performance ports remain installed, with independent switches.
This delivery is **evidence collection, not a claimed graphics fix**. Do not
report an FPS gain or restored shadows before the phone comparison.

## Why shadows first

Re-read the user's `Zelda-SNX-boot(2).txt` and existing shader-capture work.
The log says `shadows_enabled=1`. Its 242 unique emitted shadow-binding
records all bind real D24_UNORM_S8_UINT views, 2048 by 2048, as 2D arrays.
The bounded trace is not every draw and contains no GPU depth pixels. Older
analysis already correlated this address with recorded depth-only draws.
Neither trace proves the occluders were rendered into the expected layers.
No new shader upload is required just to repeat that previous analysis.

Reference inspected: [seedds/nxnative at 3eb1d76](https://github.com/seedds/nxnative/blob/3eb1d76f5ddd56277f68fefbe162ec83a54899a1/dm/gfx/nvn/nvn_mtl.m).
Its `mtl_set_depth_zero`/`shader_load` select the NVN zero-to-one or GL depth
entry; `mtl_set_origin_lower_left` and viewport/winding/presentation handle
the window origin. ScarletNX already handles those concepts through register
0x35f, vertex push constants, `vk_render_viewport` and facing state. It also
already has shadow samplers, depth views and color-depth comparison variants.
Blindly adding these again is not the next port.

The nxnative HLE backend also fills NVN driver constant tables for compute
light culling. ScarletNX executes the guest driver and resolves its constant
buffer bindings. Copying those synthetic HLE tables over real guest data is
not a justified fix. The full NativeAOT bridge remains fragment-oriented;
the native ScarletNX translator already supports vertex/compute execution.

The unanswered first question is whether the depth image **as sampled** is
empty/constant, has geometry in the wrong layers/orientation, or has plausible
contents whose shader coordinates/reference/compare state need investigation.
Shadows are a controlled first target; one depth correction is not assumed
to fix water or all lighting.

| Order | Concrete next work | Expected visual impact | Risk / difficulty |
|---|---|---|---|
| 1 | Capture shadow depth layers and producer state, then repair the proven producer or reader defect. | Projected shadows; actual result pending. | Low, opt-in diagnostic; repair depends on evidence. |
| 2 | Trace interior light culling, depth/G-buffer reads, blend and light-shaft composition against the reference. | Local light and beams. | Medium/high; do not remove compute or overwrite driver data. |
| 3 | Trace water depth/normal/environment/reflection inputs, surface views and final composition. | Water reflection, color and lighting. | Medium/high; correct each demonstrated mismatch. |

## What is installed

`tools/patch_scarletnx_zelda_shadow_capture.py` applies after binding reuse
and restores first. It adds `tools/zelda-perf/shadow_capture.h` to the pinned
runtime, without modifying shaders, persistent caches, AOT, guest writes or
wait policy. No required draw or integrity check is bypassed.

- **Capturar sombras (3 amostras; teste visual)** is OFF by default. It is
  independent of shader capture, FPS telemetry, Ryujinx and performance
  switches. The launcher passes a private directory for a new session.
- From 15 seconds after Vulkan initialization, the next eligible real depth
  view sampled by a nonindexed shadow binding is captured. Further samples
  are at least 15 seconds apart, with three maximum per process. Delay is
  elapsed time, not a promise of a specific game scene.
- Level zero, all array layers, actual scaled image dimensions; not the
  unscaled guest dimensions. D16, D24 and D32 depth aspects are supported.
  Undefined, volume/multiple-mip/unsupported images are not captured. There
  is one pending dedicated host buffer, at most 64 MiB and within the device
  allocation cap. A refused diagnostic never drops the game's draw.
- The pass ends, existing `vk_surf_use` barriers order an image-to-buffer copy,
  a COPY-write to HOST-read barrier is recorded, and exact original image use
  is restored. The original sample transition still runs. No extra explicit
  queue submit, device idle or fence/timeline wait is added.
- CPU invalidation/read/file saving run through `vk_defer_call` at normal
  frame retirement, after its existing completion wait. Nothing is written
  back into guest memory. The callback owns its buffer and copied metadata;
  it never dereferences a retired surface.
- A complete `.depth`/`.json` pair records frame/generation, dimensions/layers,
  source format, consumer shader/slot, all TIC/TSC words, and the latest
  matching recorded depth draw's VS/FS and raw viewport, depth, bias, target
  and culling registers. Unknown generations remain explicitly unknown.
  Predicated draws are identified, not treated as pixel-completion evidence.
- File writes use `.partial`; JSON is published last as a completion marker.
  The bounded ZIP exporter accepts only complete pairs from the newest
  session and includes the exported runtime log. It never falls back to old
  successful captures when the current session is empty. Existing sessions
  and caches are preserved.

Capture adds up to three pass breaks, transfer traffic and file I/O. It can
cause pauses: it is **not an FPS experiment**. `analyze_zelda_perf.py` refuses
an armed capture session. Switch capture OFF and start a fresh game process
for normal performance comparisons. Keep the original FSWZADD experiment OFF.

The [Vulkan depth-aspect copy rules](https://docs.vulkan.org/spec/latest/chapters/copies.html#copies-buffers-images)
are important here: copying D24S8 depth to a buffer produces X8_D24_UNORM_PACK32,
not guest interleaved depth/stencil bytes. The analyzer ignores the undefined
high eight bits. It prints min/max/mean, zero/one/nonfinite/out-of-range counts
and histograms separately for each layer. Optional nearest-sampled PGM previews
preserve image row order; the `range` preview rescales per-layer min/max and
is explicitly not the original depth range. A constant map alone is not
declared a rendering bug: an unused layer or a scene without occluders can
legitimately be constant.

## Exact Termux update and test

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-sombras-termux.sh
```

Install/update `Download/ZeldaRecomp/Zelda-SNX-SOMBRAS.apk`; do not uninstall
the current application. The wrapper preserves the previous binding APK as
`Zelda-SNX-BINDINGS-ANTES-SOMBRAS.apk` once, as well as the earlier references.
Existing AOT, CMake/Ninja and shader/driver caches are reused.

1. In the launcher, keep Ryujinx live OFF and shader capture OFF for this
   first native-path test. Keep resolution, Stable60 and performance options
   exactly as in the working build. Select FPS logging LEVE.
2. Set **Capturar sombras (3 amostras; teste visual): ON** and start the game.
   Go directly to the outdoor comparison spot, with Link and trees visible.
   Stay for 60 seconds and take a screenshot. Avoid the title/menu during
   those 60 seconds; captures occur on elapsed time and shadow sampling.
3. Exit through the game/menu flow, without forcibly killing its process
   immediately after a sample. Reopen the launcher and choose
   **Exportar diagnostico de sombras (.zip)**. Send `Zelda-sombras.zip` with
   the same-scene screenshot. An empty newest session is reported as empty.
4. Turn capture OFF. A light/phone-house or water scene can be captured in a
   separate run later; the first requested evidence is the outdoor map.

Optional local analysis (the ZIP can be sent without running this):

```bash
cd "$HOME/LASRecomp-Android"
python3 tools/analyze_zelda_shadows.py \
  /storage/emulated/0/Download/Zelda-sombras.zip \
  --out /storage/emulated/0/Download/Zelda-sombras-analise
```

Do not commit private captures, game shaders, ROM content or keys.

## Validation and limits

All 44 host audit tests pass, with zero skips and a real `spirv-val`.
Host validation exercises the actual capture header and actual pinned
`vk_surf_use` with delayed GPU/retirement endpoints: OFF has no recorded work,
all layers/bytes and copied metadata survive, CPU reads follow retirement,
the original image state returns, one pending buffer/three captures are
bounded, allocation/mapping/file failures preserve resource lifetimes.
The actual Java exporter compiles targeting Java 8 and runs ZIP selection,
incomplete/newest-session, size and byte-preservation regressions. Format,
preview orientation, analyzer refusal, APK markers and byte-exact full patch
stack restoration are checked. Full patched `render.c` and `renderer.c`
pass C syntax checks with the existing performance ports installed.
The capture fixture also passes ASan/UBSan; host LeakSanitizer is unavailable
under the existing `/proc` restriction.

No full Android APK/AOT rebuild, driver execution or Zelda run is done on
this host. Phone correctness, actual captures, pauses and graphical results
remain unverified. Do not describe this diagnostic as a fix or speedup.
