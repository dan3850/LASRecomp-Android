# Experimental native NVN -> OpenGL ES backend (Android only)

Branch: `android/native-opengles-backend`. Safe Vulkan starting point:
`4368fc2fcd3dbea350069633ae6a44442ca1a21e` on
`android/native-vulkan-rnd`.

## Actual current implementation
- Android settings select `Vulkan` or `OpenGL ES 3.0 — backend NVN nativo (experimental)`.
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
**This is not a playable Zelda renderer yet.** Maxwell shader translation to
GLSL ES, vertex/index buffers, texture uploads and formats, samplers,
draws/compute, blending, depth/stencil, copies and render-target aliasing
remain unimplemented or incomplete. Draw calls are counted and skipped;
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
