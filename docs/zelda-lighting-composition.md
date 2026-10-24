# Zelda: preserve the improved picture and investigate remaining composition

Updated 2026-10-24, after device feedback on the `9be351c` depth delivery.

**Follow-up:** both requested `3d0b426` scene logs have now arrived. The depth
extension is actually enabled, composition candidates and real depth inputs
are observed, and no blend fault is demonstrated. Read
[`zelda-effect-depth-evidence.md`](zelda-effect-depth-evidence.md) for the
measured results, precise limits and new optional paired depth-pixel capture.
The original request for these same two logs below is historical, completed.

## Current device evidence

The user reports that colors and water are now resolved. The supplied images
also show projected tree/character shadows that were absent in earlier
screenshots, plus foreground depth-of-field blur. The user still reports
missing shadows/reflected light, the outdoor haze visible in Eden and the
indoor window light shafts. Treat shadowing and blur as partially present;
do not claim that every shadow/reflection or post-process is now correct.

Preserve `Zelda-SNX-PROFUNDIDADE.apk` as the immediate visual reference.
The photos show phone overlay values of 57, 60 and 59 FPS. These are isolated
overlay readings, not a measured stable frame-rate comparison, simulation
rate or proof of the Vulkan extension's enabled state. No new runtime log
accompanied these photos. Do not analyze the old `1f4d2a7`/`3b02e52` detailed
logs as if they were captured after the depth correction.

Private screenshot identities, SHA-256 (no images are committed):

- `1769601.jpg`: `7cd562372f63bd38b552c13b33c53b91957a841e4dc97f5684a7cab0ec89f054`
- `1769600.jpg`: `61becece6a45865e7a5d4ce9323b2b183f44efcfbb0946b44f9c22c362ce69c5`
- `1769599.jpg`: `3e475ffc989da7ae538456558f8835350be637f1afa63aa3c1356df59c0c9942`

## Audit result and missing measurement

Existing `SNX_GFX_PASS_V1` records shader/target/depth setup, but does not
record blend factors/constants, stencil masks, alpha test or the viewport
depth actually selected. Its exact signature also does not distinguish most
of those state changes. Existing `SNX_GFX_BIND_V1` intentionally suppresses
ordinary valid 2D color reads; its original 128-entry budget serves missing,
depth and non-2D bindings. Thus the old trace cannot establish that a lighting
composition pass reads the expected intermediate color image or blends it
with the expected state. Preserve that original diagnostic and its budget.

Do not transplant nxnative's `bfac` values blindly: that function consumes
NVN API enums (its constant-color/alpha family is 0x61..0x64). ScarletNX's
`blend_factor` consumes Maxwell registers. The official
[NVIDIA clb197.h](https://github.com/NVIDIA/open-gpu-doc/blob/master/classes/3d/clb197.h)
uses D3D BLENDFACTOR/INVBLENDFACTOR 0x0e/0x0f and OGL constants
0xc001..0xc004 for these register inputs. Those existing mappings are present
in ScarletNX. No observed Maxwell 0x61 use or missing-constant-factor fix is
established; no blend enum change is justified by this audit.

The screenshot's apparent smoke may be fog, particles or another atmospheric
composition. Its exact pass and the interior shafts' failure are not yet
proven. First correlate shader IDs, actual setup and intermediate inputs in
the corrected build. No old FSWZADD experiment or arbitrary gamma/lighting
adjustment is repeated.

## Delivered passive evidence

`tools/patch_scarletnx_zelda_lighting_diag.py` applies after depth-range
preservation and restores first. It installs `lighting_diag.h` in `render.c`
and uses the existing **Registrar FPS GPU DETALHADA** mode. There is no new
visual setting or rendering experiment. OFF/LEVE returns before register,
viewport or texture inspection and produces no new diagnostic rows.

- `SNX_LIGHT_META_V1`: explicit diagnostic scope and fixed limits.
- `SNX_LIGHT_STATE_V1`: exact state families, with the first target example
  for each. Raw blend registers, constants, masks, alpha/depth/stencil tests,
  clip/origin/culling/bias/scissor state accompany the existing pipeline
  key's effective first-color blend `[enable, srcRGB, dstRGB, opRGB, srcA,
  dstA, opA, writeMask]`. The selected Vulkan viewport's two depth endpoints
  are encoded as eight-digit float bit patterns, preserving nonfinite bits
  without invalid JSON. Up to 64 distinct state families per window.
- `SNX_LIGHT_RT_V1`: up to 64 separately budgeted valid nonindexed 2D color
  render-target bindings per window, with consumer shader/stage/slot, source
  address/format/guest and scaled dimensions, and full TIC/TSC words. This
  does not capture all ordinary art textures, indexed candidates, volume
  textures or snapshots that are not marked render targets. Existing depth,
  missing-view and non-2D diagnostics continue unchanged.
- `SNX_LIGHT_V1`: attempts, emitted record counts, detail-limit flags and
  line refusals. State and RT-read budgets reset at complete telemetry windows.
  State overflow is explicit; RT overflow uses the existing
  `SNX_GFX_LIMIT_V1` with kind `lighting_color_rt`. No unbounded per-draw log.

These are CPU observations of state/descriptor preparation, not proof that a
draw executed or produced nonzero light pixels. State families deliberately
exclude target address and dimensions from their identity; the printed
target is their first example, not a complete render graph. Only the first
bound color slot is detailed. A full table means later families are unknown,
not absent. Any repair must respect those limits.

The helper performs no GPU command, allocation, resource lookup, draw skip,
image readback, synchronization change, guest write or shader edit. It reads
the existing blend pipeline key and the view the normal binding path
already resolved. Existing logging incurs extra CPU/disk work in detailed
mode; use LEVE for normal play and clean FPS comparisons. All previous
performance ports, depth correction, Stable60 and cache behavior remain.

## Exact incremental build and two short scene logs

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-iluminacao-termux.sh
```

Output: `Download/ZeldaRecomp/Zelda-SNX-ILUMINACAO-DIAG.apk`.
The existing depth APK is preserved once as
`Zelda-SNX-PROFUNDIDADE-ANTES-ILUMINACAO.apk`. Install as an update. The wrapper
uses the depth/buffer builders, retains current options and reuses generated
AOT plus Gradle/CMake/Ninja/shader caches; no clean or game LLVM regeneration.

1. Keep **Preservar faixa de profundidade ON**, native translator and all
   current performance options. Keep shader/shadow captures OFF.
2. Select **Registrar FPS GPU DETALHADA**, start the game, enter the telephone
   house and stay there about 45 seconds. Exit normally and save the log as
   `Zelda-luz-casa.txt`.
3. In a fresh game process visit the outdoor forest comparison spot where
   Eden shows haze. Stay about 45 seconds, exit and export
   `Zelda-nevoa.txt`. Existing photos can be reused; no repeated shader ZIP
   is needed at this point.
4. Return FPS logging to **LEVE** for normal play. The new observer becomes
   inactive. Preserve the reference APK and keep the new depth option ON.

Analyze each exported log with `tools/analyze_zelda_perf.py` if desired. It
keeps the new scope/limits, counts capped windows rather than summing boolean
flags as work, and excludes incomplete observer summaries from complete
windows. The Java exporter already retains every complete `SNX_*_V1` row;
its 8-MiB export cap and explicit truncation marker remain unchanged.

## Validation and precise next step

57 host audit tests pass, zero skips with a real SPIR-V validator. Tests run
the actual observer and original exact signature helper: detailed OFF does
no inspection/logging, blend/constants/target-slot changes remain distinct,
inputs remain byte-identical, valid handle zero is preserved, irrelevant
reads are excluded, separate 64-entry bounds and window reset hold, and all
emitted JSON is complete. Native ASan/UBSan pass (LeakSanitizer disabled under
the host `/proc` restriction). Full patched `render.c`/`renderer.c` pass C
syntax checks; shell syntax, signed-APK profile gates, analyzer completeness
and whole-stack apply-twice/byte-exact rollback pass.

The actual Java log exporter also compiled/executed with 139 generated
diagnostic rows; the longest was 1,254 bytes and every row survived intact
in the exported telemetry block. No private game capture is a test fixture.
No full Android/AOT build or new phone result is claimed from these checks.

Resume with the two scene logs. Identify shader/state/input differences for
the missing effect, then inspect its already captured program or request
only the specific missing evidence. Correct the demonstrated blend/depth/
stencil/input/translation defect in a separate reversible change. Additional
color-pixel capture may be needed if all setup/inputs appear plausible; this
observer does not substitute CPU state for GPU pixel evidence. Remaining
targets: atmospheric haze, indoor shafts/reflected light, residual shadowing
and localized blur differences. Colors/water are accepted as improved by
the user and must not be reworked without a new demonstrated regression.
