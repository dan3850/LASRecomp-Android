# Experimental native NVN -> OpenGL ES backend (Android only)

Branch: `android/native-opengles-backend`. Safe Vulkan starting point:
`4368fc2fcd3dbea350069633ae6a44442ca1a21e` on
`android/native-vulkan-rnd`.

## Actual current implementation
- Android settings select `Vulkan` or `OpenGL ES 3.2 — backend NVN nativo (experimental)`.
- The Activity passes the selected API to the C entry point, before loading the
  game engine. `LARECOMP_RENDERER=gles` selects the GLES path.
- SDL creates a **GL window and GLES context**, not a Vulkan surface/device.
- The game still calls the same NVN HLE functions. The GLES executor can
  process render target bindings, float RGBA8 colour clears, simple texture
  clears, CPU buffer copies and GPU-timestamp-compatible counters.
- It presents its **own GLES framebuffer textures** to the Android window.
  There is no Vulkan drawing, PixelCopy, overlay or hybrid presentation.
- Writes `<app files>/graphics/gles.txt` with the actual GLES driver and
  operation counts. The existing graphics ZIP includes this file.

## Not implemented — important
**This is not a playable Zelda renderer yet.** There is now a strictly
limited Maxwell GLSL ES 3.2 translation path with vertex/index draws for
supported non-textured, single-colour, no-depth/no-blend commands.
Texture uploads/formats, samplers, GMEM, compute, blending, depth/stencil,
copies and render-target aliasing remain unimplemented or incomplete.
Unsupported draw calls are counted and skipped;
expect a dark/incomplete image. The engine may also encounter unsupported
commands before reaching gameplay. No fallback silently starts Vulkan.

## Build and test
Use `bash compilar-lasrecomp-termux.sh` on native Termux ARM64 after switching
to this branch, reusing the existing SDK/NDK and build caches. The script links
the Android ARM64 `libGLESv3.so` import library for the GLES path and retains
the Vulkan backend unchanged. Select GLES before pressing JOGAR, reproduce
the issue and export `SALVAR DIAGNÓSTICO GRÁFICO (ZIP)`.

Static source-isolation check:
`python3 tests/test_gles_backend_isolation.py`. It is not a driver test.

## Return to safe baseline
`git switch android/native-vulkan-rnd`; compile using the same existing
incremental build script. No force/reset/clean is necessary.

## SDL3: Android EGL initialization
The Termux script **must compile SDL 3.2.22 with**
`-DSDL_OPENGLES=ON` (not `OFF`). On Android this enables
`SDL_VIDEO_OPENGL_EGL` and `SDL_VIDEO_OPENGL_ES2`, which are necessary for
`SDL_WINDOW_OPENGL` and `SDL_GL_CreateContext`. SDL remains compiled with
`SDL_VULKAN=ON` on the same Android build and Vulkan remains selectable.

A previous build failed before any NVN rendering with
`SDL_CreateWindow: OpenGL support is either not configured ... (android)`.
The new build script passes native ARM64 GLES libraries to SDL's linker,
reconfigures its **existing** CMake/Ninja cache, checks the SDL GLES option and
recompiles only changed SDL objects. Do not delete the SDL cache or Gradle
artifacts.

## SDL3 iconv / Termux compilation
For `SDL_iconv.c` undeclared iconv_open/iconv_close/iconv when enabling
GLES, the SDL3 CMake configuration sets `SDL_SYSTEM_ICONV=OFF` and
uses its bundled iconv converter. NDK EGL/GLES header lookup uses
`-idirafter` so Termux libc headers keep precedence. SDL3 gets
incrementally reconfigured and compiled with the existing CMake/Ninja cache.

## Milestone 2: real, limited Maxwell graphics path (not yet verified on Adreno)
- Added `ShaderKey.glsl_es` to emit `#version 320 es` and share existing
  Maxwell arithmetic translation without Vulkan-only descriptor sets.
  Vulkan GLSL 460 remains the default when this bit is unset.
- Added a GLES-only NVN draw executor in `runtime/nvn/gles/draw.c`.
  It processes program, vertex attribute/stream/buffer, cbuf, viewport
  and render-target commands. For a supported non-textured, single-color,
  no-depth/no-blend draw, it compiles the **actual translated Maxwell shaders**
  and issues `glDrawArrays` / `glDrawElements` on host GL VBOs.
- Program caching avoids recompiling the same guest program repeatedly;
  unsupported features and compilation errors are cached as failures.
- `graphics/gles.txt` now reports `native_maxwell_draws`,
  `gles_programs_linked`, `gles_programs_failed` and `unsupported_draws`.
  These counters distinguish real translated draws from skipped commands.
- This path has only source-level checks so far. No Termux build or device
  validation was performed by the assistant. It may fail GLSL compilation
  or show no real draws: read the driver log before claiming success.

**Pending for a playable Zelda**: robust texture formats/deswizzle,
samplers, GMEM/SSBO and shaderInt64 emulation, depth and stencil,
blending, render target formats/aliases, compute, synchronization,
advanced primitive variants, accurate cbuf driver constants, resource
lifetime and optimized vertex transfers. The strict subset refuses draws
needing these instead of inventing their results.

## Milestone 3: depth, color attachments, and fixed-function draw state

After 2040 GLES frames in the user's Adreno 840 test, the log still showed
`nativeNVN=0 programs=0 failed=0` and hundreds of thousands of skipped
draws. In the previous version, `gles_draw_execute` explicitly rejected any
depth attachment, depth testing, blend enable, non-full channel mask, or
culling **before calling the Maxwell shader translator**. This meant the
backend could never reach the shader stage for normal Zelda scenes.

This update:
- Creates GLES images using the actual supported NVN format instead of
  pretending all render targets (including depth-stencil!) are `GL_RGBA8`.
  Handles key RGB11F, RGBA16F, RGBA8, and depth-stencil formats, with an
  explicit unsupported return rather than a silent approximation.
- Attaches native depth/depth-stencil textures to the color framebuffer.
- Executes NVN depth/stencil clears and applies depth/stencil testing, cull
  mode, front face, scissor, channel mask, and blend equations/factors during
  the supported GLES draw path.
- Logs precise rejection reasons in the periodic `[gles]` status output and
  in `graphics/gles.txt`, so a new test can distinguish a framebuffer failure
  from an incompatible shader or vertex layout.

This does **not** imply the game is graphically correct or playable.
Texture sampling, deswizzling, GMEM, compute and synchronization still need
implementation. Keep the safe Vulkan branch intact and test only in the
experimental GLES branch.

## Startup diagnosis and GLES presentation state (October 18)
A user-provided diagnostic cut off in native game initialization (at the
savedata reads), before any current GLES draw counters were included; the
historical Vulkan section of the diagnostic is unrelated to the current
GLES run. This code adds durable startup NVN command-list checkpoints after
1, 16, 128 and 1024 executed lists, plus early frame checkpoints (1, 16,
64). They appear in `graphics/gles.txt` and are also logged to the runtime
log. This avoids relying on the last 16 KB of a noisy engine trace.

Corrected final fullscreen GLES presentation to explicitly reset culling,
stencil test and all-channel color write mask. The native render state must
not mask or cull the presentation triangle. **This does not implement
textures/GMEM/compute or prove a playable scene.**

### Shader error evidence without game assets
The GLES shader translator now writes at most 24 diagnostic events to
`graphics/gles-shaders.txt` (included in the usual graphics ZIP). Events
include the stage, driver error summary and shader addresses, **not** ROM
data, shader source, game libraries or extracted assets. This helps separate
unsupported Maxwell features from GLSL ES compilation/link errors.

## Milestone 4: native CPU-backed Maxwell 2D texture sampling
The user's current diagnostic continues to show black with audio. The
independent GLES backend explicitly **rejected every Maxwell shader using a
texture**; moreover `gles_upload_rgba` was a stub. Native raster state work
alone therefore could not produce the game's textured scene.

Implemented GLES-side texture sampling for a **strict 2D subset**:
- Reads NVN texture/sampler handles from the existing descriptor pools
  using the same indices as the Vulkan executor, without calling Vulkan.
- Converts real Tegra block-linear guest texel data via `tegra_deswizzle`.
  For BCn and ASTC LDR, reuses existing portable BCn and ASTC decoders;
  selects the appropriate native GLES image format and uploads the pixels.
- Binds actual GL sampler and texture objects to translated Maxwell
  `sampler2D` uniforms. Texture formats/views not yet represented accurately
  remain rejected; no placeholder textures or fabricated shader colors.
- Tracks CPU texture versions to avoid uploading unchanged images on every
  draw and protects GPU-produced render targets from being overwritten by
  stale CPU-backed texture data.
- Adds sample_ok/sample_failed/sample_cached/upload_bytes to GLES diagnostics.

The following still require implementation: all non-2D targets (arrays,
cubes, 3D), arbitrary views and sampler border modes, GPU memory writes and
copy synchronization, compute, shader global memory (GMEM), binding stage
conflicts, and several Vulkan-only GLSL constructs. Therefore **black screen
or incomplete graphics may persist**; results must be checked from
`graphics/gles.txt` and `graphics/gles-shaders.txt` in a new diagnostic ZIP.

### Native RGBA video frames and depth-framebuffer binding
The existing `gles_upload_rgba` callback previously dropped decoded RGBA
video frames entirely, causing black video with working audio even when the
native GLES context was valid. It now copies pixels into an eight-slot,
mutex-protected queue; the GLES render thread performs `glTexSubImage2D`
before NVN command execution and before presentation. Texture finalization
removes queued entries under the same lock. Frames uploaded/dropped are
counted in the diagnostics. No OpenGL calls occur from the decode callback.

Also corrected the native color+depth framebuffer attachment path:
creating a depth texture changes the current GL framebuffer; the color
framebuffer is now explicitly rebound before attaching it. Unsupported
texture formats may remain valid for sampling even when they cannot be
used as render targets. OpenGL state and the safe Vulkan branch stay separate.

## Milestone 5: real NVN image-copy render graph and presentation tracing
The user's latest engine log contains many successful Maxwell GLSL ES
**program links** and reports of `glDrawArrays/glDrawElements` being
issued. That proves program creation and the draw path were reached, not
that the final screen received valid pixels. The previous GLES executor
ignored `CMD_COPY_TEXTURE_TO_TEXTURE` and `CMD_DOWNSAMPLE` entirely.
Vulkan handles both and Zelda uses intermediate render targets.

Implemented:
- Decode the same `TexRef` command payload already recorded by NVN.
- Perform real GPU-side FBO `glBlitFramebuffer` copies and downsample
  operations, respecting source/destination regions and validating supported
  formats, base-level views, nonmultisampled textures and FBO completeness.
- Upload real CPU-backed source pixels first when appropriate; never copy
  uninitialized source contents or invent image data.
- Track `copy_attempted`, `copy_succeeded`, `copy_failed` in
  `graphics/gles.txt` and the periodic log.
- Track whether the window texture presented had an actual GPU/CPU write,
  its format, native GL object and presentation GL error.
- Reset sampler binding 0 for the fullscreen presentation, so NVN shader
  samplers do not override the final blit's sampling state.
- Check GLES draw errors for early/periodic Maxwell draws instead of
  labeling every submitted draw as a success without driver verification.

This does not complete the renderer. In particular, GPU buffer->texture
transfers, complex array/cube views, GMEM, compute, and the full Zelda
postprocessing pipeline remain to be implemented. No actual Android build
or device gameplay validation has been performed for this milestone.
The restored Vulkan reference branch remains untouched.

## Milestone 6: uniform updates and CPU buffer -> native GL texture
The engine-log excerpt received after milestone 5 still contains
`real NVN draw ok`, the previous logging string; milestone 5 changed it
to `GLES NVN draw issued`. The log appears to contain older execution
records, so it does not prove the latest GPU copy changes ran. The
`graphics/gles.txt` file now writes a unique `backend_milestone` label
to confirm exactly which GLES backend is executing.

Two more differences from the Vulkan command executor were corrected:
- `CMD_UPDATE_UNIFORM_BUFFER` now copies recorded NVN uniform bytes into
  guest-mapped memory at the correct point in the command stream, with
  explicit bounds checks. Previously it was ignored, allowing shader
  uniforms to remain stale even after successful program links.
- `CMD_COPY_BUFFER_TO_TEXTURE` and `CMD_SET_COPY_STRIDES` now process a
  strict subset of NVN 2D, single-layer, uncompressed R8/RG8/RGB8/RGBA8
  uploads using proper pixel-store stride. Other formats/levels are
  rejected rather than displaying invalid pixels.
- Corrected NVN format `0x19` to native GL_RGB8 (three bytes per pixel);
  it had mistakenly been handled as GL_RGBA8 and in the four-byte video
  upload path, which could fail due to mismatched pixel layout.
- Added `uniform_updates_ok`, `uniform_updates_failed`,
  `buf_to_tex_attempts`, `buf_to_tex_ok`, and `buf_to_tex_failed`
  metrics in `graphics/gles.txt`.

The native GLES backend is **still incomplete** (GMEM, compute, array
views, further formats and GPU readback paths). Static checks do not
replace an actual Termux APK build or Adreno 840 gameplay validation.

## Milestone 7: texture-view rejection and Tegra 2D arrays
Source: user-supplied `LASRecomp-grafico-20261018-101550.zip`, with
`backend_milestone=nvn-uniform-buffer2texture-rgb8`:
`native_maxwell_draws=299001`, `unsupported_draws=588491`,
`rejected_texture_binding=141251`, but **`sample_ok=0` and
`sample_failed=0`**. This proves texture-bound draws are rejected
**before calling** the actual GLES sampler function; successfully linking
47 shader programs and copying 16285 image regions does not solve that.

The texture binding path formerly rejected *every* descriptor with
`NvnTexEntry.has_view`, even identity `NVNtextureView` registrations.
It also rejected all `sampler2DArray` shader bindings. This milestone:
- Accepts NVN texture views that preserve the original format, complete
  mip/layer range, and identity/original channel swizzle. Partial views
  requiring `glTextureView`, incompatible formats and feedback loops remain
  rejected to avoid incorrect images.
- Creates real GLES `GL_TEXTURE_2D_ARRAY` resources for NVN target 4,
  uploads each Tegra block-linear array layer (using the correct per-layer
  offset and existing ASTC/BCn decoders) and binds native 2D array samplers.
  Existing one-layer 2D sampling is preserved.
- Splits rejected texture counts into: shader kind, texture pool,
  invalid handle, target/descriptor, incompatible view, framebuffer
  feedback, and actual GLES upload/sampler failure.
- Identifies this APK via `backend_milestone=nvn-gles-array-identityviews-v1`
  in `graphics/gles.txt`.

This is a narrowly supported path. Non-identity texture views, cube/3D
sampling, compute, GMEM, and shader program link failures remain separate
work. The user log also contains `EGL_BAD_SURFACE` later in the session;
it does not account for persistent black from first frame. No Adreno
device build or visual confirmation has been performed by the assistant.

## Milestone 8: full NVNtextureView flag recognition and GLES channel swizzles
The user's `LASRecomp-grafico-20261018-102916.zip` confirms milestone 7
running on an Adreno 840. Counts: 74768 native Maxwell draw calls,
45551 rejections attributed to `texture_reject_view`, **0 sampled
textures**, 8197 actual NVN texture copies, and zero sampled draw
driver errors. The 332 decoded RGBA video frames were uploaded; this
does not mean the game scene was correctly rendered.

Root cause verified against `objects.c`: the view API defines six
setmask bits (levels 1, layers 2, format 4, swizzle 8,
depth/stencil 16 and target 32), but the GLES validation rejected
any bit outside the first four (mask ~15). This rejects valid
NVN view descriptors *before* attempting to use their sampled data.

- Recognize all six defined bits (mask ~63), honor target overrides only
  when matching the actual GL storage class, and honor depth-mode
  overrides only when they do not change the sampled depth/stencil aspect.
- Translate the actual NVN channel swizzles (ZERO, ONE, RED, GREEN, BLUE,
  ALPHA) into the four GLES 3.2 per-component parameters
  `GL_TEXTURE_SWIZZLE_R/G/B/A`, with an explicit
  identity swizzle when NVN leaves all channels unset.
- Detect conflicting simultaneous swizzles for the same underlying GL
  texture within one shader and reject rather than draw incorrect pixels.
- Distinguish remaining incompatible view levels, layers, format, target,
  depth mode, unknown flags and per-draw swizzle conflicts. Emit up to 24
  distinct rejected view shapes to the runtime log with their flag values.
- Write `backend_milestone=nvn-gles-viewflags-swizzle-v2` into the
  `graphics/gles.txt` snapshot.

This removes an identified blanket rejection but does not implement
non-base mipmap sampling, 2D views of selected array layers, GLSL ES
unsupported global memory/compute, or full render correctness. It has
not been built or tested on the Android GPU by the assistant.

## Milestone 9: native Tegra mip chains, based on 11:02 diagnostic
The user-provided `LASRecomp-grafico-20261018-110214.zip` shows
20,495 view rejections (all `view_reject_level`), while
`texture_views_accepted=20156` and `sample_ok=20156`.
A repeated rejected view has `mask=0x3f`, `base_level=0`,
`num_levels=10`, matching the texture's complete 10-level mip chain.
The GLES path previously allocated/uploaded **only mip level 0** and
incorrectly rejected this entirely valid complete-chain view.

The experimental GLES renderer now allocates a complete native GL
mipmap chain up to the actual Tegra-reported level count (limited by
the texture dimensions and 16 levels), and uploads every level of
every array layer, using `tegra_level` per-level offsets and the
existing Tegra deswizzler / ASTC and BCn decoders. Sampler minification
filters select nearest/linear mipmap filtering for NVN modes 2–5, with
non-mip fallback for images that only contain GPU-rendered base levels.
The view validator accepts level 0 plus all levels, including views
that explicitly specify `num_levels=10`, but still rejects arbitrary
mip subranges without a true per-view GL resource. Diagnostic
`mip_textures_uploaded` and `mip_levels_uploaded` distinguish actual
full-chain uploads from metadata-only validation.

Other remaining blockers from this log include 27,695 fixed-function
rejections, 10,875 index rejections, 100 failed shader programs,
2,705 skipped compute operations and later EGL_BAD_SURFACE events.
A complete playable render has **not** been proven; no Android device
build was run by the assistant.
