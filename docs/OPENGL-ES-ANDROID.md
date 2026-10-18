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
