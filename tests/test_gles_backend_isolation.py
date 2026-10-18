#!/usr/bin/env python3
"""Source-isolation checks for the experimental NVN -> OpenGL ES backend.
These do not replace an Android compilation or gameplay test.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
def source(path):
    return (root / path).read_text(encoding="utf-8")

gl = source("runtime/nvn/gles/gles.c")
dev = source("runtime/nvn/vulkan/device.c")
exe = source("runtime/nvn/vulkan/exec.c")
native = source("android/game/game_entry.c")
screen = source("android/src/com/retroaura/lasrecomp/GameImportActivity.java")
activity = source("android/src/com/retroaura/lasrecomp/GameSDLActivity.java")
build = source("compilar-lasrecomp-termux.sh")

for token in ("SDL_GL_CreateContext", "glCreateProgram(", "glGenFramebuffers(",
              "glFramebufferTexture2D(", "glClear(", "glDrawArrays(",
              "SDL_GL_SwapWindow(", "case CMD_CLEAR_COLOR", "case CMD_SET_RENDER_TARGETS"):
    assert token in gl, f"Missing native GLES operation: {token}"
for call in ("vkCreateInstance(", "vkCreateDevice(", "vkCmdDraw(", "PixelCopy.request("):
    assert call not in gl, f"GLES backend must not call {call}"
assert "SDL_WINDOW_OPENGL" in dev and "SDL_WINDOW_VULKAN" in dev
assert 'if (gles_selected()) {\n        gles_present(t);\n        return;' in dev
assert 'if (gles_selected()) { gles_execute(handle); return; }' in exe
assert 'strcmp(value, "gles")' in native
assert "gles-native" in screen and "use_native_gles" in screen
assert "getNativeRenderer()" in activity and "OpenGLGameOverlay" not in activity
assert '"$GLES_STUB"' in build and "runtime/nvn/gles" in build
draw = source("runtime/nvn/gles/draw.c")
translator = source("runtime/nvn/maxwell/translate.c")
maxwell_h = source("runtime/nvn/maxwell/shader.h")
for token in ("gles_draw_execute(", "gles_draw_state(", "native_draws++",
              "glVertexAttribPointer(", "glVertexAttribIPointer(",
              "glDrawElements(", "glDrawArrays(", "maxwell_translate("):
    assert token in draw, f"Native Maxwell draw missing: {token}"
assert "gles_draw_execute(r, false)" in gl
assert "gles_draw_execute(r, true)" in gl
assert "glsl_es" in translator and "glsl_es" in maxwell_h
assert "#version 320 es" in translator
assert "GL_MAX_UNIFORM_BUFFER_BINDINGS" in draw
assert "stream_bytes[stream]" in draw
for forbidden in ("vkCmdDraw", "PixelCopy", "gl_FragCoord = vec4(", "fake Maxwell"):
    assert forbidden not in draw
print("GLES native separation and limited Maxwell GLSL ES draw path: source assertions passed")

fixed = source("runtime/nvn/gles/draw.c")
for token in ("glDepthFunc(", "glBlendFuncSeparate(", "glStencilOpSeparate(",
              "glCullFace(", "glScissor(", "gles_draw_rejection_summary("):
    assert token in fixed, f"Missing NVN fixed-function GLES support: {token}"
for token in ("GL_DEPTH24_STENCIL8", "GL_R11F_G11F_B10F", "GL_RGBA16F",
              "gles_clear_depth(", "glFramebufferTexture2D("):
    assert token in gl, f"Missing native attachment handling: {token}"
assert "gles_draw_framebuffer(st.color[0], st.depth" in fixed
print("GLES depth, blend and native framebuffer source assertions passed")

assert "glDisable(GL_CULL_FACE);" in gl
assert "glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);" in gl
assert "nvn_lists_executed" in gl
assert "g_frames == 1" in gl
print("GLES presentation-state and early-checkpoint source checks passed")

assert "gles-shaders.txt" in source("runtime/nvn/gles/draw.c")
assert "gles-shaders.txt" in source("android/src/com/retroaura/lasrecomp/GraphicsDiagnostics.java")
assert "shader_diagnostic(\"vertex-translate\"" in draw
assert "shader_diagnostic(\"fragment-compile\"" not in draw or "compile_shader(GL_FRAGMENT_SHADER" in draw
print("GLES driver shader diagnostic source checks passed")

# Native texture path: use existing verified Tegra/BCn/ASTC decoders, no
# Vulkan/PixelCopy substitutes or fake solid-color textures.
gles = source("runtime/nvn/gles/gles.c")
draws = source("runtime/nvn/gles/draw.c")
for token in ("tegra_deswizzle(", "astc_decode_ldr(", "las_bcn_decode(",
              "glTexSubImage2D(", "GL_UNPACK_ALIGNMENT", "gles_sample_texture(",
              "glGenSamplers(32", "tex->target != 1"):
    assert token in gles, f"Native Tegra 2D texture support missing: {token}"
for token in ("bind_textures(", "gles_sample_texture(", "CMD_BIND_TEXTURES",
              "CMD_SET_TEXTURE_POOL", "CMD_SET_SAMPLER_POOL", "R_TEXTURE",
              "gles_mark_texture_written("):
    assert token in draws, f"Native Maxwell 2D sampler path missing: {token}"
assert "p->fs->ntex || p->vs->ntex" not in draws
assert "if (!bind_textures(p)) return false;" in draws
assert "glBindSampler((GLuint)unit,sm);" in gles
print("GLES native CPU textures and real Maxwell sampler binding: source checks passed")

# Video surfaces are produced by a non-GL thread: pixel data must be copied
# into a bounded queue and uploaded on the actual GLES render thread.
for token in ("pthread_mutex_lock(&video_mutex)", "GLES_VIDEO_QUEUE = 8",
              "gles_flush_video_queue(", "video_frames_uploaded=",
              "video_uploaded++", "glTexSubImage2D(GL_TEXTURE_2D,0,0,0,q->w"):
    assert token in gles, f"GLES video frame queue missing: {token}"
assert gles.count("gles_flush_video_queue();") >= 2
assert "void gles_mark_texture_written(NvnTexture *tex);" in gles
assert "glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);" in gles
print("Native GLES video upload ownership and GL-thread queue: source checks passed")

# The real Switch NVN graph copies intermediate render targets into
# the window texture; GL draws alone cannot replace those copy commands.
gles = source("runtime/nvn/gles/gles.c")
draws = source("runtime/nvn/gles/draw.c")
for token in ("case CMD_COPY_TEXTURE_TO_TEXTURE:", "case CMD_DOWNSAMPLE:",
              "glBlitFramebuffer(", "GL_READ_FRAMEBUFFER",
              "GL_DRAW_FRAMEBUFFER", "copy_succeeded=",
              "copy_failed=", "present_missing=", "present_written=",
              "glBindSampler(0, 0);", "[gles-present] frame=",
              "copy_view_base_only(", "g_present_gl_errors++"):
    assert token in gles, f"Native GLES render graph / presentation missing: {token}"
for token in ("gl_draw_errors=", "glGetError()", "draw rejected by GL driver"):
    assert token in draws, f"NVN GL error validation missing: {token}"
assert "if (!src || !dst || src == dst" in gles
assert "if (!s->gpu_written && !s->cpu_uploaded)" in gles
print("GLES FBO render graph and real presentation diagnostics: source checks passed")

# Uniform buffer updates and buffer-to-texture copies must run at their
# recorded NVN command position, before later shaders consume the content.
gles = source("runtime/nvn/gles/gles.c")
for token in ("case CMD_UPDATE_UNIFORM_BUFFER:", "gles_update_uniform(",
              "case CMD_COPY_BUFFER_TO_TEXTURE:", "gles_copy_buffer_texture(",
              "case CMD_SET_COPY_STRIDES:", "glTexSubImage2D(GL_TEXTURE_2D,0,x,y,w,h",
              "GL_UNPACK_ROW_LENGTH", "uniform_updates_ok=",
              "buf_to_tex_ok=", "backend_milestone=nvn-uniform-buffer2texture-rgb8",
              "GL_RGB8, GL_RGB, GL_UNSIGNED_BYTE"):
    assert token in gles, f"Missing native GLES NVN GPU buffer transfer: {token}"
assert "case 0x19: case 0x25:" not in gles
assert "q->tex->format==0x25 || q->tex->format==0x19" not in gles
print("GLES NVN uniform-update, buffer-texture copy, RGB8 mapping source checks passed")
