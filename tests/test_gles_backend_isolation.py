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
