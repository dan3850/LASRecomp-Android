# Zelda shadow evidence and viewport-depth correction

Updated 2026-10-24. The user reports a substantial FPS improvement from the
current build, with missing shadows and unchanged water/colors/blur. Preserve
that performance reference. This step corrects one demonstrated numerical
mapping error; restored Android graphics still need device confirmation.

## Evidence actually received

`Zelda-sombras.zip` SHA-256:
`74a26058d59caf15de3afb99208767cc6133dafbd9fe6fc9786e7343e454e29d`.
It contains three complete D24S8 depth-aspect pairs, one 2048x2048 layer each,
and the same `0e0dfa4` log previously analyzed. Private depth/shader data stays
outside git. The analyzer masks the undefined upper byte of X8_D24 correctly.

| Sample / frame | Minimum / maximum depth | Pixels different from clear 1.0 |
|---|---|---|
| 1 / 764 | 0.468843488 / 1.0 | 58.5226% |
| 2 / 1656 | 0.664243499 / 1.0 | 2.1960% |
| 3 / 2541 | 0.457090763 / 1.0 | 53.9931% |

All samples have nonconstant finite depths and matching recorded producer
generations, without predication. Samples 1 and 3 visibly contain terrain,
trees and buildings in the depth previews. Sample 2 has a small isolated
silhouette; its clear area alone is not evidence of a failed pass. No new
same-frame color screenshot was included, so do not identify every object or
claim the orientation, bias or consumer coordinates are correct from this.

The three consumer hashes match existing private shader captures exactly
after accounting for the capture filename's key mix; no new shader dump was
needed. Their shadow bindings resolve the same real depth surface. The TSC
requests a LESS comparison and linear min/mag filtering. Existing sampler,
array-view and shader-coordinate paths are present; none is replaced with
an always-lit/always-shadowed result.

## Demonstrated mapping error

Each recorded producer has:

- `r[0x35f]=0`: clip Z in the negative-W to positive-W convention.
- Z scale `r[0x282]=1.0`, Z offset `r[0x285]=0.0`.
- Clip-depth endpoint registers `r[0x302]=0.0`, `r[0x303]=1.0`.
- Existing `vertex_depth_fix` maps clip Z to `(z+w)/2` for Vulkan clipping.

`vk_render_viewport` derives the corresponding viewport endpoints as -1 and
1, then clamps them to 0 and 1. That changes the composed transform:

```text
guest window depth:             z_ndc * 1 + 0
existing Vulkan result:         (z_ndc + 1) / 2
with preserved viewport range:  ((z_ndc + 1) / 2) * 2 - 1 = z_ndc
```

For a synthetic occluder at depth 0.2, the existing path stores 0.6 instead
of 0.2 before depth format conversion/bias. A receiver reference of 0.4 then
passes LESS against 0.6 although it should fail against 0.2. This demonstrates
how the mapping can hide shadows. Those numbers are a controlled example,
not sampled receiver coordinates from the phone.

This is not a reason to remove clip-space conversion: doing so changes the
clipping volume. Keep the existing shader and preserve its matching viewport
range with the Vulkan device extension, when available.

Primary references:

- [NVIDIA clb197.h](https://github.com/NVIDIA/open-gpu-doc/blob/master/classes/3d/clb197.h):
  `SET_VIEWPORT_Z_CLIP`, `SET_VIEWPORT_SCALE_Z`, `SET_VIEWPORT_OFFSET_Z` and
  `SET_VIEWPORT_CLIP_CONTROL` are separate controls.
- [Vulkan coordinate/viewport transformations](https://docs.vulkan.org/spec/latest/chapters/vertexpostproc.html):
  the default Vulkan depth mapping uses `maxDepth-minDepth` and `minDepth`.
- [VK_EXT_depth_range_unrestricted](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_depth_range_unrestricted.html):
  permits viewport endpoints outside 0..1 without changing primitive clipping.

## Small, reversible implementation

`tools/patch_scarletnx_zelda_depth_range.py` applies after the buffer pool and
restores first. It extends the existing device-extension enumeration, enables
`VK_EXT_depth_range_unrestricted` only if advertised and explicitly requested,
and preserves finite computed endpoints in that mode. OFF, unsupported
devices and nonfinite endpoints retain the original clamp behavior. The
extension-name array is enlarged from 24 to 32 entries for the added name.
No additional physical-device query or per-frame feature negotiation occurs.

No shader instructions, SPIR-V, pipeline/shader cache format or keys change.
The clip conversion, XY viewport/origin, culling, bias, depth test/write,
samplers, buffers, copies, barriers, waits, Stable60 and AOT remain. This adds
no readback or submission. Because shaders are unchanged, cache deletion or
a new translation namespace would be unnecessary and is not performed.

Runtime: `SNX_VK_DEPTH_RANGE=1`. Launcher: **Preservar faixa de profundidade**.
Default ON only in the new depth profile (`Zelda-DepthRange.txt`), honoring
saved preferences. Other profiles default OFF; set it OFF explicitly when
rebuilding an old comparison if the preference was previously saved ON.

`SNX_DEPTH_RANGE_META_V1` reports requested/supported/enabled independently.
The device's extension support is not known from the old phone log. A new
log with `supported=0, enabled=0` means this correction did not activate; do
not call that a failed test of the corrected mapping. `STATE_V1` prints up to
four outside-range states. Per-window `SNX_DEPTH_RANGE_V1` counts viewport
setups and outside-range setups, not visible pixels or successfully executed
draws. The FPS analyzer keeps this metadata and requires complete same-mode
windows while continuing to reject shadow-capture sessions.

## Exact incremental Termux build and visual comparison

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-profundidade-termux.sh
```

Output: `Download/ZeldaRecomp/Zelda-SNX-PROFUNDIDADE.apk`.
Install as an update. The wrapper preserves the existing buffer APK once as
`Zelda-SNX-BUFFERS-ANTES-PROFUNDIDADE.apk`, then reuses the buffer/bindings
builders, Gradle/CMake/Ninja caches and generated game AOT. No clean or game
LLVM regeneration. Existing reference APKs and shader caches are retained.

1. Keep all performance options and Stable60 as in the improved build. Keep
   Ryujinx live OFF, both captures OFF and FPS logging LEVE.
2. Set **Preservar faixa de profundidade OFF**, start a fresh game process,
   visit the outdoor comparison spot and save a screenshot plus log.
3. Exit normally, change only this option to ON, start a fresh process and
   repeat the same scene. Save the screenshot and log. Check light beams,
   water and blur separately rather than assume they share one defect.
4. Confirm `requested=1, supported=1, enabled=1` and nonzero
   `unrestricted_setups` in the ON log before attributing visual changes to
   this path. If unsupported, retain the working OFF reference and inspect
   other supported ways to preserve the transform/clipping together.
5. OFF plus a fresh process is the immediate rollback. No cache deletion or
   shader recapture is needed. If depth mapping is active but shadows remain
   absent, compare another depth ZIP and the consumer coordinates/reference,
   then bias/application, rather than repeat FSWZADD.

## Validation and remaining work

53 host audit tests pass, zero skips, with real SPIR-V Tools validation.
The actual pinned device-selection snippet and actual before/after viewport
functions run through 160 viewport vectors, including the captured state,
negative depth scales, reversed ranges, both clip modes, resolution/origin
changes, missing/invalid/OFF settings, missing extension and nonfinite
fallbacks. OFF is byte-exact in these cases. The synthetic original mapping
fails the intended 0.2 depth; the new one preserves it. Selection performs
the same two mocked extension enumeration calls. Reports are bounded and
inactive when performance logging is OFF.

The full patch stack applies twice and restores every source byte. Existing
private captures are not committed as fixtures. Signed-APK asset/marker gates,
analyzer mode/completeness checks and Zelda-only Java wiring are checked.
ASan/UBSan pass for the native fixture (LeakSanitizer disabled under the host's
existing `/proc` restriction). Fully patched `device.c`, `render.c` and
`renderer.c` pass C syntax checks with real Vulkan/VMA/generated declarations;
changed activities parse, and shell syntax checks pass. The first full test
attempt referenced an absent old validator path; restoring a real validator
and rerunning the unchanged checks produced the passing result above.

No Android APK/game run, physical GPU pixel rendering or FPS improvement is
claimed from these host checks. Next: device visual OFF/ON and capability log;
if needed, consumer coordinate/reference/bias evidence. Lighting/culling,
water composition/color and depth-of-field blur remain separate investigations.
Memory content-check costs under pagemap denial and clean performance A/B
remain pending, preserving the user's qualitative FPS improvement.
