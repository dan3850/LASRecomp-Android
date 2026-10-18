#!/usr/bin/env python3
"""Source-isolation checks for the experimental NVN -> OpenGL ES backend.
These do not replace an Android compilation or gameplay test.
"""
from pathlib import Path
import re

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
# Do not mistake API names mentioned in comments for backend calls.
# Check executable C source (including string literals), not explanatory comments.
draw_code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", draw)
for forbidden in ("vkCmdDraw", "PixelCopy", "gl_FragCoord = vec4(", "fake Maxwell"):
    assert forbidden not in draw_code, f"Forbidden GLES executable token: {forbidden}"
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
              "glTexParameteri(want,swizzle_pnames[c],rgba[c])"):
    assert token in gles, f"Missing GLES 3.2 component swizzle: {token}"
assert "glTexParameteriv(host->target,GL_TEXTURE_SWIZZLE_RGBA" not in gles
assert "GLenum want=target == 4 ? GL_TEXTURE_2D_ARRAY : GL_TEXTURE_2D;" in gles
assert "glBindTexture(want,sample_texture);" in gles
assert "glTexParameteri(want,swizzle_pnames[c],rgba[c]);" in gles
assert "host->alias_swizzle_valid=true;" in gles
assert "normalize_swizzle(" in draws
assert "view_reject_target=" in draws
assert "view_reject_swizzle_conflict=" in draws
assert "backend_milestone=nvn-gles-packed-gmem-ldg-v6" in gles
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
assert "static char buffer[3584];" in draw
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
              "mip_levels_uploaded=", "backend_milestone=nvn-gles-packed-gmem-ldg-v6"):
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

# The 11:45 Adreno GLES log shows 28,901 depth/stencil rejects,
# 7,813 base-instance rejections, and 5,159 rejected target formats.
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
translator=source("runtime/nvn/maxwell/translate.c")
for token in ("bool gles_color_target_supported(uint32_t format)",
              "f.attachment == GL_COLOR_ATTACHMENT0"):
    assert token in gles, f"Missing GLES color target format support: {token}"
for token in ("gles_color_target_supported(st.color[color_index]->format)",
              "const bool depth_attachment=st.depth",
              "const bool stencil_attachment=st.depth",
              "if (st.ds[0] && depth_attachment)",
              "if (st.ds[3] && stencil_attachment)",
              "depth_without_attachment++", "stencil_without_attachment++",
              "depth_without_attachment=", "stencil_without_attachment="):
    assert token in draws, f"Missing attachment-aware native GLES state: {token}"
assert "st.color[color_index]->format != 0x19" not in draws
assert "if (!compare || !st.depth)" not in draws
for token in ("gl_InstanceID) + gles_base_instance",
              "uniform highp uint gles_base_instance;"):
    assert token in translator, f"Missing GLES firstInstance shader support: {token}"
for token in ("uint64_t first_instance_raw=indexed ? r->x[5] : r->x[3]",
              "first_instance_raw>UINT32_MAX", "uint32_t base_instance=",
              'glGetUniformLocation(p->gl_program,"gles_base_instance")',
              "glUniform1ui(base_uniform,base_instance)",
              "attributes(p,maxindex,first,instances,base_instance)",
              "(uint64_t)base_instance*stride",
              "indexed_base_instance_draws++", "arrays_base_instance_draws++"):
    assert token in draws, f"Missing real NVN firstInstance handling: {token}"
assert "|| r->x[5])" not in draws
assert "else if (r->x[3])" not in draws
print("GLES attachment-aware depth/stencil, native color formats and firstInstance checks passed")

# Native shader link: fragment IPA flat/noperspective interpolation must
# also be declared on the vertex varying. Do not modify Vulkan shaders.
draws=source("runtime/nvn/gles/draw.c")
for token in ("align_gles_varying_qualifiers(", "flat in vec4 v%d;",
              "noperspective in vec4 v%d;", "flat ", "noperspective ",
              "out vec4 v%d;", "gles_shader_varyings_aligned=",
              "if (!align_gles_varying_qualifiers(p->vs,p->fs))"):
    assert token in draws, f"Missing GLES varyings alignment: {token}"
assert "default: return GL_ALWAYS; // NVN/Vulkan compare_fn fallback" in draws
assert "default: return GL_KEEP; // NVN/Vulkan stencil_op fallback" in draws
print("GLES interpolation interface and stencil fallback checks passed")

# 12:25 real Adreno GLES snapshot: 20,700 stencil rejects, because
# GL_ZERO is a valid stencil enum with value 0, but the old renderer
# tested !fail/!pass/!depth_fail and rejected those draws as invalid.
draws=source("runtime/nvn/gles/draw.c")
translator=source("runtime/nvn/maxwell/translate.c")
assert "case 2: return GL_ZERO;" in draws
assert "if (!cmp || !fail || !pass || !depth_fail)" not in draws
assert "stencil_zero_op_states++" in draws
assert "stencil_zero_op_states=" in draws
# The Qualcomm GLSL link error "Unscoped name checking failed" can occur
# when VS/FS declare anonymous cbN global uniform members at different
# array sizes. Keep block ABI names V_CBn/F_CBn but make its members scoped.
# Vulkan GLSL still intentionally uses the anonymous cbN declaration.
# Only the GLES-specific branch must use scoped block instances.
assert 'uvec4 cb%d[%u]; };\\n' in translator
gles_cbuf = translator.split('            const char *prefix = stage == STAGE_FRAGMENT ? "f" : "v";', 1)[1].split('        } else', 1)[0]
assert 'uvec4 cb%d[%u]; };\\n' not in gles_cbuf
assert 'uvec4 words[%u]; } %s_cb%d;' in translator
assert '#define cb%d %s_cb%d.words' in translator
assert 'stage == STAGE_FRAGMENT ? "F" : "V"' in translator
assert 'const char *prefix = stage == STAGE_FRAGMENT ? "f" : "v";' in translator
assert 'layout(std140, set = %d, binding = %d) uniform CB%d' in translator
assert 'snprintf(name,sizeof name,"%s_CB%d",stage ? "F" : "V", k);' in draws
print("GLES GL_ZERO stencil and scoped per-stage constant block checks passed")

# Adreno 840 12:38 diagnostic: the GLES renderer linked 72 Maxwell
# programs and ran 256979 native draws, but lost 165610 others.
# Translate non-GMEM unsigned carry and funnel shifts without uint64_t.
# This must remain GLES-only: Vulkan still uses the original 64-bit path.
translator=source("runtime/nvn/maxwell/translate.c")
draw=source("runtime/nvn/gles/draw.c")
assert translator.count("if (c->key && c->key->glsl_es)") >= 3
for token in ("uaddCarry(av, bv, ca)", "uaddCarry(mid, extra, cb)",
              "uaddCarry(av,bv,ca)", "uaddCarry(s0,cv,cb)",
              "uaddCarry(s1,extra,cd)",
              "cc = (ca + cb) & 1u", "cc = (ca + cb + cd) & 1u",
              "uint shf32_r(uint hi, uint lo, uint sh)",
              "uint shf32_l(uint hi, uint lo, uint sh)",
              "shf32_r(%s, %s, %s)", "shf32_l(%s, %s, %s)"):
    assert token in translator, f"Missing GLES 32-bit equivalent: {token}"
for token in ("ulong sum = ulong", "ulong(%s) << 32"):
    assert token in translator, "The Vulkan shader translator path must remain unchanged"
for token in ("shader_reject_gmem=", "shader_reject_sampler=",
              "shader_reject_int64=", "shader_reject_subgroup=",
              "shader_disabled_draws=",
              "shader_disabled_draws++",
              "if (!p->gl_program) {"):
    assert token in draw, f"Missing GLES unsupported shader diagnostic: {token}"

# Deterministic algebraic reference for GLSL uaddCarry chains/32-bit SHF.
# These tests check the intended math, not a compiled shader.
import random
random_test = random.Random(0xC0FFEE)
mask32 = (1 << 32) - 1
def add32(x, y):
    total = x + y
    return total & mask32, total >> 32
for _ in range(4096):
    a,b,c,extra = (random_test.getrandbits(32) for _ in range(4))
    mid,ca = add32(a,b)
    out,cb = add32(mid,extra)
    total = a+b+extra
    assert out == (total & mask32) and ((ca+cb)&1) == ((total>>32)&1)
    mid,ca = add32(a,b)
    mid,cb = add32(mid,c)
    out,cd = add32(mid,extra)
    total = a+b+c+extra
    assert out == (total & mask32) and ((ca+cb+cd)&1) == ((total>>32)&1)
    shift=random_test.randrange(32)
    expected_right=(((a<<32)|b)>>shift)&mask32
    expected_left=(((((a<<32)|b)<<shift)>>32)&mask32)
    got_right=b if shift==0 else ((b>>shift)|(a<<(32-shift)))&mask32
    got_left=a if shift==0 else ((a<<shift)|(b>>(32-shift)))&mask32
    assert expected_right == got_right and expected_left == got_left
print("GLES ES3 32-bit carry/funnel shift regression: 4096 reference cases passed")

# Adreno GLES 12:57: 1,095 real sampling draws were lost on feedback.
# They now read a GLES framebuffer snapshot of the previous attachment
# pixels, not the forbidden live render texture (or fabricated values).
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
for token in ("bool gles_bind_feedback_snapshot(",
              "glBlitFramebuffer(0,0,h->width,h->height",
              "glBindFramebuffer(GL_READ_FRAMEBUFFER,h->framebuffer)",
              "glBindFramebuffer(GL_DRAW_FRAMEBUFFER,h->feedback_framebuffer)",
              "h->target!=GL_TEXTURE_2D", "h->levels!=1",
              "glTexImage2D(GL_TEXTURE_2D,0,(GLint)f.internal",
              "h->feedback_color", "h->feedback_framebuffer",
              "glBindTexture(GL_TEXTURE_2D,h->feedback_color)",
              "glDeleteTextures(1, &t->feedback_color)",
              "glDeleteFramebuffers(1, &t->feedback_framebuffer)",
              "feedback_copy_ok=", "feedback_copy_failed=",
              "feedback_allocated=", "bad_alloc:"):
    assert token in gles, f"Missing native GLES render-target snapshot: {token}"
for token in ("gles_bind_feedback_snapshot(tex,i,swizzle)",
              "for(int attachment=0;attachment<st.ncolor;attachment++)",
              "bool feedback_depth = tex==st.depth;", "texture_rejection[T_FEEDBACK]++"):
    assert token in draws, f"Missing NVN feedback draw binding: {token}"
assert "tex==st.color[0] || tex==st.depth" not in draws
print("Native GLES same-pass color feedback snapshot and rejection path checks passed")

# Subgroup availability must come from the GLES driver's extension list,
# never inferred from Vulkan's distinct enabled GPU capabilities.
gles=source("runtime/nvn/gles/gles.c")
for token in ("glGetIntegerv(GL_NUM_EXTENSIONS,&n)",
              "glGetStringi(GL_EXTENSIONS,(GLuint)i)",
              'gles_extension("GL_KHR_shader_subgroup_basic")',
              'gles_extension("GL_KHR_shader_subgroup_shuffle")',
              'gles_extension("GL_KHR_shader_subgroup_shuffle_relative")',
              "gl_ext_subgroup_basic=", "gl_ext_subgroup_shuffle="):
    assert token in gles, f"Missing GLES shader extension discovery: {token}"
print("GLES runtime subgroup/int64 driver capability report source checks passed")

# Read-only native GLES GMEM: a packed GPU SSBO of actual committed guest
# storage ranges and an indexed GMap table, not Vulkan execution or a
# fictitious zero-filled heap. STG/compute remain unsupported.
draws=source("runtime/nvn/gles/draw.c")
translator=source("runtime/nvn/maxwell/translate.c")
planner=source("runtime/nvn/vulkan/gmem.h")
for token in ("if (c->key && c->key->glsl_es && !store)",
              "uaddCarry(%s, 0x%08xu, addcarry)",
              "usubBorrow(alo, 0x%08xu, borrow)",
              "uint fw = ok ? gfind(ga & ~3u",
              "gfast_.w[fw + %uu]",
              "if (es && !c->uses_gmem_store)"):
    assert token in translator, f"Missing GLES 2x32 packed LDG: {token}"
for token in ("#include \"../../kernel.h\"",
              'include "../vulkan/gmem.h"', "gmem_plan(&plan,ranges,n",
              "glBindBufferBase(GL_SHADER_STORAGE_BUFFER,0,gmem_ssbo)",
              'glGetProgramResourceIndex(p->gl_program,GL_SHADER_STORAGE_BLOCK,"GFast")',
              'glGetUniformBlockIndex(p->gl_program,"GMap")',
              "GL_MAX_SHADER_STORAGE_BLOCK_SIZE", "GL_MAP_INVALIDATE_BUFFER_BIT",
              "glUnmapBuffer(GL_SHADER_STORAGE_BUFFER)",
              "gmem_snapshot_draws=", "gmem_snapshot_bytes=",
              "gmem_snapshot_reject_range=", "gmem_snapshot_reject_gl=",
              "if (!bind_uniforms(p) || !bind_readonly_gmem(p) ||"):
    assert token in draws, f"Missing GLES GMEM SSBO snapshot: {token}"
assert "if (needs_sampler || unsupported_gmem || needs_int64 || needs_subgroup)" in draws
assert "gmem_writes ||" in draws
assert "p->vs->uses_gmem_store || p->fs->uses_gmem_store" in draws
assert "vkCmd" not in re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", draws)
assert "static inline bool gmem_plan(" in planner
assert "vkCmd" not in planner and "VkBuffer" not in planner

# Two-word arithmetic must reproduce signed 24-bit displacement addition,
# then subtract the NVN heap base, including borrow through the high word.
import random
random_addr=random.Random(0xBA51C)
mask32=0xffffffff
heap_base=0x7240000000
for _ in range(2048):
    high=random_addr.getrandbits(32)
    low=random_addr.getrandbits(32)
    off=random_addr.randint(-0x800000,0x7fffff)
    w=low+(off&mask32)
    alo=w&mask32
    carry=w>>32
    ahi=(high+(-1 if off<0 else 0)+carry)&mask32
    diff=(alo-0x40000000)&mask32
    borrow=int(alo<0x40000000)
    diff_hi=(ahi-0x72-borrow)&mask32
    expected=(((high<<32)|low)+off-heap_base)&0xffffffffffffffff
    assert (diff_hi<<32)|diff == expected
print("GLES packed read-only GMEM and 64-bit guest address tests passed")

# GLES 3.2 provides glBindBufferBase but NOT desktop OpenGL's
# glShaderStorageBlockBinding. Bind GFast explicitly in GLSL ES 3.20.
translator=source("runtime/nvn/maxwell/translate.c")
draws=source("runtime/nvn/gles/draw.c")
assert "layout(std430, binding = 0) %sbuffer GFast" in translator
assert "glBindBufferBase(GL_SHADER_STORAGE_BUFFER,0,gmem_ssbo);" in draws
draw_code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", draws)
assert "glShaderStorageBlockBinding(" not in draw_code
assert 'glGetProgramResourceIndex(p->gl_program,GL_SHADER_STORAGE_BLOCK,"GFast")' in draws
assert 'layout(std430, set = %d, binding = %d) %sbuffer GFast' in translator
print("GLES storage buffer binding 0 without desktop-only API: source checks passed")

# Adreno 840 13:58: 684 native NVN draw calls were rejected by the
# same GLenum zero-valued-factor mistake previously fixed for stencil.
# GL_ZERO is allowed by GLES blend functions; unknown NVN factors are not.
draws=source("runtime/nvn/gles/draw.c")
translator=source("runtime/nvn/maxwell/translate.c")
gles=source("runtime/nvn/gles/gles.c")
for token in ("case 1: return GL_ZERO;", "default: return GL_INVALID_ENUM;",
              "cs==GL_INVALID_ENUM", "cd==GL_INVALID_ENUM",
              "as==GL_INVALID_ENUM", "ad==GL_INVALID_ENUM"):
    assert token in draws, f"Missing correct GLES GL_ZERO blend handling: {token}"
assert "if (!cs || !cd || !as || !ad || !ce || !ae)" not in draws
# The real device rejected a fragment sampler declaration with missing
# precision, so later references to the sampler were also invalid.
assert 'sp(&s, "uniform highp %s t%d;' in translator
assert 'sp(&s, "uniform %s t%d;' not in translator
assert 'layout(set = %d, binding = %d) uniform %s t%d;' in translator
# GLES depth-stencil copy must preserve stencil on GPU, not only depth.
assert "(GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT)" in gles
assert "s->attachment==GL_DEPTH_STENCIL_ATTACHMENT" in gles
assert "glBlitFramebuffer(sx,sy,sx+sw,sy+sh,dx,dy,dx+dw,dy+dh,mask,filter);" in gles
print("GLES zero-valued blending, highp samplers, and depth-stencil copy checks passed")

# The real Adreno GLES 14:08 snapshot discarded 1086 draws sampling the
# currently attached depth/stencil texture. GLES must snapshot actual GPU
# pixels to a second depth FBO, not sample attached memory or fake zeros.
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
for token in ("bool gles_bind_depth_feedback_snapshot(",
              "glFramebufferTexture2D(GL_FRAMEBUFFER,h->attachment,GL_TEXTURE_2D,",
              "GL_DEPTH_BUFFER_BIT |", "GL_STENCIL_BUFFER_BIT : 0",
              "glBlitFramebuffer(0,0,h->width,h->height,0,0,h->width,h->height,",
              "glReadBuffer(GL_NONE);",
              "glBindTexture(GL_TEXTURE_2D,h->feedback_color);"):
    assert token in gles, f"Missing native GLES depth feedback: {token}"
assert "bool feedback_depth = tex==st.depth;" in draws
assert "gles_bind_depth_feedback_snapshot(tex,i,swizzle)" in draws
assert "if(tex==st.depth)" not in draws
print("GLES native depth-stencil feedback snapshot regression checks passed")

# Adreno GLES 14:08: 2230 2D-array sampling attempts but zero bound.
# Native ES3.2 textures have immutable targets. A single-layer 2D image
# can be represented by a separately allocated one-layer 2D array with
# real GPU texel copies (including mip chain), never faked samples.
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
for token in ("#include <GLES3/gl32.h>", "glCopyImageSubData(",
              "GL_TEXTURE_2D_ARRAY,host->array_alias",
              "host->alias_epoch!=host->content_epoch",
              "host->content_epoch++;", "glDeleteTextures(1, &t->array_alias)",
              "bool array_alias=target==4 && tex->target==1",
              "gles_single_layer_array_alias(tex,host)",
              "GLuint sample_texture=array_alias ? host->array_alias : host->color;"):
    assert token in gles, f"Missing real GLES single-layer array alias: {token}"
assert "bool single_layer_array=array && tex && tex->target==1" in draws
assert "tex->layout.layers==1" in draws
print("GLES true one-layer sampler2DArray alias and GPU invalidation checks passed")

# GPU-written video and buffer-to-texture updates must also invalidate any
# single-layer sampling alias. That alias already snapshots color feedback
# on glCopyImageSubData; don't accidentally rebind a sampler2D there.
gles=source("runtime/nvn/gles/gles.c")
draws=source("runtime/nvn/gles/draw.c")
assert "tex->content_epoch++; // video replaces the sampled image" in gles
assert "host->content_epoch++; // invalidate one-layer sampler-array alias" in gles
assert "feedback_color && !single_layer_array &&" in draws
print("GLES array aliases track video/copy updates and preserve sampler type")
