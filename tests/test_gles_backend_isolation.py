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
