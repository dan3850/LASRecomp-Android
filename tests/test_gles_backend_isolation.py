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
assert "gles_draw_framebuffer(st.color, st.ncolor, st.depth" in fixed
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
              "buf_to_tex_ok=",
              "GL_RGB8, GL_RGB, GL_UNSIGNED_BYTE"):
    assert token in gles, f"Missing native GLES NVN GPU buffer transfer: {token}"
assert "case 0x19: case 0x25:" not in gles
assert "q->tex->format==0x25 || q->tex->format==0x19" not in gles
print("GLES NVN uniform-update, buffer-texture copy, RGB8 mapping source checks passed")

# User's Adreno GLES diagnostic: 141251 binds rejected without even
# entering gles_sample_texture (sample_ok=0, sample_failed=0). Remove the
# blanket NVNtextureView exclusion and accept only same-resource views.
draws=source("runtime/nvn/gles/draw.c")
gles=source("runtime/nvn/gles/gles.c")
for token in ("compatible_texture_view(", "texture_reject_kind=",
              "texture_reject_pool=", "texture_reject_handle=",
              "texture_reject_descriptor=", "texture_reject_view=",
              "texture_reject_feedback=", "texture_reject_upload=",
              "texture_views_accepted=", "texture_array_attempts=",
              "texture_array_bound="):
    assert token in draws, f"NVN GLES texture-view diagnostics missing: {token}"
assert "entry->has_view || tex->target!=1" not in draws
assert "if (!compatible_texture_view(entry,swizzle,&why))" in draws
assert "rejected_view(entry,why);" in draws
for token in ("GL_TEXTURE_2D_ARRAY", "glTexImage3D(", "glTexSubImage3D(",
              "tegra_layer_size(", "layer_size*layers>size",
              "host->target != want"):
    assert token in gles, f"Native GLES 2D array support missing: {token}"
assert "g_sample_ok++;" in gles
print("Native NVN identity views and GLES 2D array layer decoding: source checks passed")

# NVNtextureView has six explicitly supported setmask flags, including
# depth/stencil (16) and target (32). Rejecting these as unknown previously
# dropped every sampled draw, with sample_ok=0 and 45551 view rejections.
gles = source("runtime/nvn/gles/gles.c")
draws = source("runtime/nvn/gles/draw.c")
assert "(v->setmask & ~63u)" in draws
assert "(v->setmask & 32u)" in draws
assert "(v->setmask & 16u)" in draws
for token in ("GL_TEXTURE_SWIZZLE_R", "GL_TEXTURE_SWIZZLE_G",
              "GL_TEXTURE_SWIZZLE_B", "GL_TEXTURE_SWIZZLE_A",
              "glTexParameteri(host->target,swizzle_pnames[c],rgba[c])"):
    assert token in gles, f"Missing GLES 3.2 component swizzle: {token}"
assert "glTexParameteriv(host->target,GL_TEXTURE_SWIZZLE_RGBA" not in gles
assert "normalize_swizzle(" in draws
assert "view_reject_target=" in draws
assert "view_reject_swizzle_conflict=" in draws
assert "backend_milestone=nvn-gles-full-mips-v3" in gles
assert "backend_milestone=nvn-gles-array-identityviews-v1" not in gles
print("GLES NVN six view flags and native swizzle translation: source assertions passed")

# Catch mismatches between the native sampled-texture signature in the
# draw dispatcher and its definition before a Termux C compilation.
assert ("extern bool gles_sample_texture(NvnTexture *tex, NvnSamplerDesc *sampler, int unit,\n"
        "                                bool shadow, uint8_t type,\n"
        "                                const uint8_t swizzle[4]);") in draw
assert ("bool gles_sample_texture(NvnTexture *tex, NvnSamplerDesc *sampler,\n"
        "                         int unit, bool shadow, uint8_t target,\n"
        "                         const uint8_t swizzle[4])") in gl
assert "static char buffer[3072];" in draw
print("GLES texture-swizzle ABI and diagnostic buffer source assertions passed")

# Android GLES 3.2 provides separate swizzle selectors, not desktop GL's
# aggregate GL_TEXTURE_SWIZZLE_RGBA selector.
for token in ("GL_TEXTURE_SWIZZLE_R", "GL_TEXTURE_SWIZZLE_G",
              "GL_TEXTURE_SWIZZLE_B", "GL_TEXTURE_SWIZZLE_A"):
    assert token in gl
assert "glTexParameteriv(host->target,GL_TEXTURE_SWIZZLE_RGBA" not in gl
print("Native GLES3 per-component swizzle API regression checks passed")

# The Adreno 840 11:02 diagnostics showed 20,495 V_LEVEL rejections for
# a legitimate complete 10-level NVN view. Make sure base level zero and
# full-chain texture views are accepted, but partial/nonzero-base views
# remain explicitly rejected until real GL texture views are implemented.
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
assert "v->num_levels != tex->layout.levels" in draws
assert "v->num_levels > 1" not in draws
for token in ("for (GLint level=0; level<t->levels; ++level)",
              "tegra_level(&tex->layout,(uint32_t)level)",
              "for(uint32_t level=0; level<tex->layout.levels; level++)",
              "glTexImage2D(t->target, level",
              "glTexImage3D(t->target, level",
              "glTexSubImage2D(host->target,(GLint)level",
              "glTexSubImage3D(host->target,(GLint)level",
              "GL_LINEAR_MIPMAP_LINEAR", "GL_TEXTURE_MAX_LEVEL",
              "mip_levels_uploaded=", "backend_milestone=nvn-gles-full-mips-v3"):
    assert token in gles, f"Missing NVN native full mip-chain support: {token}"
print("GLES complete Tegra mip chain and full-view source assertions passed")

# Native NVN path must not throw away MRT draws or base-vertex indices.
# The Adreno 840 11:13 log contained 15086 target-layout failures,
# 5940 index failures and 48699 fixed-state rejections. These are
# real GLES operations and verified guest index rebasing, not fake draws.
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
for token in ("glDrawBuffers(ncolor,attachments);",
              "glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0+i",
              "t->attached_colors[i]", "glReadBuffer(GL_COLOR_ATTACHMENT0);"):
    assert token in gles, f"Missing real GLES multi-render-target path: {token}"
for token in ("gles_draw_framebuffer(st.color, st.ncolor, st.depth",
              "for(int i=0;i<st.ncolor;i++) gles_mark_texture_written",
              "glEnable(GL_SAMPLE_ALPHA_TO_COVERAGE)",
              "glDisable(GL_SAMPLE_ALPHA_TO_COVERAGE)",
              "int32_t base_vertex = indexed ? (int32_t)r->x[4] : 0",
              "index_value(src,ty,i)+base_vertex",
              "GL_UNSIGNED_INT", "rebased_index_draws++",
              "rejected_target_fbo=", "rejected_fixed_multisample=",
              "rejected_fixed_polygon=", "rejected_fixed_depth=",
              "rejected_fixed_stencil=", "rejected_base_instance="):
    assert token in draws, f"Missing GLES MRT / A2C / base vertex support: {token}"
assert "r->x[4] || r->x[5]" not in draws
print("GLES MRT, alpha-to-coverage and indexed base-vertex paths: source assertions passed")
