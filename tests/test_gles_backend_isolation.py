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
print("GLES native separation: source assertions passed")
