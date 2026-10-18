// Native Maxwell -> GLSL ES 3.2, vertex buffers and non-textured draw path.
// Only complete, supported shaders are submitted. No substitute/fake shaders.
// Unsupported texture/GMEM/compute/blend/depth paths fail closed and are logged.
#include "draw.h"
#include "../maxwell/shader.h"
#include <GLES3/gl32.h>
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <sys/stat.h>

extern bool gles_draw_framebuffer(NvnTexture *const colors[8], int ncolor,
                                  NvnTexture *depth, int *w, int *h);
extern bool gles_sample_texture(NvnTexture *tex, NvnSamplerDesc *sampler, int unit,
                                bool shadow, uint8_t type,
                                const uint8_t swizzle[4]);
extern bool gles_color_target_supported(uint32_t format);
extern void gles_mark_texture_written(NvnTexture *tex);
extern uint32_t nvn_window_origin(void);
extern uint32_t nvn_depth_mode(void);

typedef struct { uint64_t addr, size; } Range;
typedef struct {
    NvnProgram *program;
    NvnTexture *color[8], *depth;
    int ncolor, nattrib, nstream;
    uint32_t attrib[16], stream[16][2];
    Range vbuf[16], ubuf[6][18], sbuf[6][16];
    uint64_t tex[6][32];
    NvnDescPool *tpool, *spool;
    float viewport[16][4];
    int32_t scissor[16][4];
    uint8_t ds[8], poly[4], color_state[4], blend[8][8], ms[0x18];
    uint32_t channel_mask;
    float depth_range[16][2], blend_color[4];
    uint32_t stencil_ref[2], stencil_mask[2], stencil_vmask[2];
} DrawState;
static DrawState st;
static GLuint uniform_buffers[36], vertex_buffers[16], index_buffer, vao;
static uint64_t native_draws, shaders_ok, shaders_failed, rejection[13];
static uint64_t checked_draws, gl_draw_errors;
static uint64_t mrt_draws, rebased_index_draws, rejected_base_instance;
static uint64_t depth_without_attachment, stencil_without_attachment;
static uint64_t indexed_base_instance_draws, arrays_base_instance_draws;
static uint64_t reject_target_layout, reject_target_format, reject_target_fbo;
enum { FIX_MULTISAMPLE, FIX_POLYGON, FIX_BLEND, FIX_DEPTH, FIX_STENCIL, FIX_SCISSOR, FIX_COUNT };
static uint64_t reject_fixed[FIX_COUNT];
enum { T_KIND, T_POOL, T_HANDLE, T_DESCRIPTOR, T_VIEW, T_FEEDBACK, T_UPLOAD, T_REASON_COUNT };
static uint64_t texture_rejection[T_REASON_COUNT];
static uint64_t texture_views_accepted;
enum { V_UNKNOWN, V_LEVEL, V_LAYER, V_FORMAT, V_TARGET, V_DEPTH, V_SWIZZLE_CONFLICT, V_REASON_COUNT };
static uint64_t view_rejection_reason[V_REASON_COUNT];
static uint64_t texture_array_attempts, texture_array_bound;
static GLenum last_gl_draw_error;
enum { R_NO_PROGRAM, R_TARGET, R_SHADER_FEATURE, R_TRANSLATE, R_COMPILE, R_TOPOLOGY,
       R_INDICES, R_VERTEX_FORMAT, R_VERTEX_RANGE, R_UBO, R_DEPTH_BLEND, R_CACHE, R_TEXTURE };
#define PROGRAM_SLOTS 512
typedef struct {
    NvnProgram *nvn;
    uint64_t vs_addr, fs_addr;
    uint32_t attr_key;
    GLuint gl_program; // 0 is permanent failure for this program combination
    ShaderInfo *vs, *fs;
} Program;
static Program programs[PROGRAM_SLOTS];
static unsigned num_programs;
static uint64_t attempts;
static unsigned shader_diagnostics_recorded;

// Text-only shader diagnostics. Do not export copyrighted guest binaries,
// translated shader source or ROM data into the user-visible diagnostic ZIP.
static void shader_diagnostic(const char *phase, uint64_t guest_vs, uint64_t guest_fs,
                              const char *reason) {
    if (shader_diagnostics_recorded++ >= 24) return;
    mkdir("graphics", 0755);
    FILE *f = fopen("graphics/gles-shaders.txt", "a");
    if (!f) return;
    fprintf(f, "event=%u phase=%s vs=%" PRIx64 " fs=%" PRIx64 "\n",
            shader_diagnostics_recorded, phase, guest_vs, guest_fs);
    if (reason) {
        // Keep individual logs small and readable; GLSL driver errors often
        // include source lines or lengthy verbose dumps.
        fprintf(f, "reason=%.512s\n", reason);
    }
    fclose(f);
}

uint64_t gles_draw_native_count(void) { return native_draws; }
uint64_t gles_draw_program_count(void) { return shaders_ok; }
uint64_t gles_draw_shader_failure_count(void) { return shaders_failed; }
const char *gles_draw_rejection_summary(void) {
    static char line[240];
    snprintf(line, sizeof line,
        "reject target=%" PRIu64 " fixed=%" PRIu64 " no-prog=%" PRIu64
        " features=%" PRIu64 " translation=%" PRIu64 " compile=%" PRIu64
        " vertex=%" PRIu64 " indices=%" PRIu64 " texture=%" PRIu64
        " tex_kind=%" PRIu64 " tex_view=%" PRIu64 " tex_handle=%" PRIu64,
        rejection[R_TARGET], rejection[R_DEPTH_BLEND], rejection[R_NO_PROGRAM],
        rejection[R_SHADER_FEATURE], rejection[R_TRANSLATE], rejection[R_COMPILE],
        rejection[R_VERTEX_FORMAT] + rejection[R_VERTEX_RANGE], rejection[R_INDICES],
        rejection[R_TEXTURE], texture_rejection[T_KIND], texture_rejection[T_VIEW],
        texture_rejection[T_HANDLE]);
    return line;
}
const char *gles_draw_rejection_stats(void) {
    static char buffer[3072];
    snprintf(buffer, sizeof buffer,
        "maxwell_draw_attempts=%" PRIu64 "\n"
        "rejected_no_program=%" PRIu64 "\nrejected_target=%" PRIu64
        "\nrejected_shader_feature=%" PRIu64 "\nrejected_translation=%" PRIu64
        "\nrejected_compilation=%" PRIu64 "\nrejected_topology=%" PRIu64
        "\nrejected_indices=%" PRIu64 "\nrejected_vertex_format=%" PRIu64
        "\nrejected_vertex_range=%" PRIu64 "\nrejected_ubo=%" PRIu64
        "\nrejected_depth_blend=%" PRIu64 "\nrejected_cache=%" PRIu64
        "\nrejected_target_layout=%" PRIu64
        "\nrejected_target_format=%" PRIu64
        "\nrejected_target_fbo=%" PRIu64
        "\nrejected_fixed_multisample=%" PRIu64
        "\nrejected_fixed_polygon=%" PRIu64
        "\nrejected_fixed_blend=%" PRIu64
        "\ndepth_without_attachment=%" PRIu64
        "\nstencil_without_attachment=%" PRIu64
        "\nrejected_fixed_depth=%" PRIu64
        "\nrejected_fixed_stencil=%" PRIu64
        "\nrejected_fixed_scissor=%" PRIu64
        "\nindexed_base_instance_draws=%" PRIu64
        "\narrays_base_instance_draws=%" PRIu64
        "\nrebased_index_draws=%" PRIu64
        "\nrejected_base_instance=%" PRIu64
        "\nmrt_draws=%" PRIu64
        "\nrejected_texture_binding=%" PRIu64
        "\ntexture_reject_kind=%" PRIu64
        "\ntexture_reject_pool=%" PRIu64
        "\ntexture_reject_handle=%" PRIu64
        "\ntexture_reject_descriptor=%" PRIu64
        "\ntexture_reject_view=%" PRIu64
        "\ntexture_reject_feedback=%" PRIu64
        "\ntexture_reject_upload=%" PRIu64
        "\ntexture_views_accepted=%" PRIu64
        "\nview_reject_unknown=%" PRIu64
        "\nview_reject_level=%" PRIu64
        "\nview_reject_layer=%" PRIu64
        "\nview_reject_format=%" PRIu64
        "\nview_reject_target=%" PRIu64
        "\nview_reject_depth=%" PRIu64
        "\nview_reject_swizzle_conflict=%" PRIu64
        "\ntexture_array_attempts=%" PRIu64
        "\ntexture_array_bound=%" PRIu64
        "\ngl_draw_checked=%" PRIu64 "\ngl_draw_errors=%" PRIu64
        "\ngl_last_draw_error=%u\n",
        attempts, rejection[R_NO_PROGRAM], rejection[R_TARGET],
        rejection[R_SHADER_FEATURE], rejection[R_TRANSLATE],
        rejection[R_COMPILE], rejection[R_TOPOLOGY], rejection[R_INDICES],
        rejection[R_VERTEX_FORMAT], rejection[R_VERTEX_RANGE],
        rejection[R_UBO], rejection[R_DEPTH_BLEND], rejection[R_CACHE],
        reject_target_layout, reject_target_format, reject_target_fbo,
        reject_fixed[FIX_MULTISAMPLE], reject_fixed[FIX_POLYGON],
        reject_fixed[FIX_BLEND], depth_without_attachment,
        stencil_without_attachment, reject_fixed[FIX_DEPTH],
        reject_fixed[FIX_STENCIL], reject_fixed[FIX_SCISSOR],
        indexed_base_instance_draws, arrays_base_instance_draws,
        rebased_index_draws, rejected_base_instance, mrt_draws,
        rejection[R_TEXTURE], texture_rejection[T_KIND], texture_rejection[T_POOL],
        texture_rejection[T_HANDLE], texture_rejection[T_DESCRIPTOR],
        texture_rejection[T_VIEW], texture_rejection[T_FEEDBACK],
        texture_rejection[T_UPLOAD], texture_views_accepted,
        view_rejection_reason[V_UNKNOWN], view_rejection_reason[V_LEVEL],
        view_rejection_reason[V_LAYER], view_rejection_reason[V_FORMAT],
        view_rejection_reason[V_TARGET], view_rejection_reason[V_DEPTH],
        view_rejection_reason[V_SWIZZLE_CONFLICT],
        texture_array_attempts, texture_array_bound,
        checked_draws, gl_draw_errors, (unsigned)last_gl_draw_error);
    return buffer;
}

static void defaults(void) {
    memset(&st, 0, sizeof st);
    for (int i = 0; i < 16; i++) {
        st.viewport[i][2] = 1280; st.viewport[i][3] = 720;
        st.scissor[i][2] = 16384; st.scissor[i][3] = 16384;
    }
    st.channel_mask = 0xffffffffu;
    st.poly[1] = 1; st.poly[2] = 2;
    st.ds[1] = 1; st.ds[2] = 2;
    st.stencil_mask[0] = st.stencil_mask[1] = 0xff;
    st.stencil_vmask[0] = st.stencil_vmask[1] = 0xff;
    for (int i=0;i<16;i++) st.depth_range[i][1]=1.f;
    for (int i=0;i<8;i++) {
        st.blend[i][1]=2; st.blend[i][2]=1;
        st.blend[i][3]=2; st.blend[i][4]=1;
        st.blend[i][5]=1; st.blend[i][6]=1;
    }
}
void gles_draw_init(void) {
    defaults();
    mkdir("graphics", 0755);
    FILE *f = fopen("graphics/gles-shaders.txt", "w");
    if (f) {
        fputs("backend=GLES-3.2\nshader_log=metadata-and-driver-errors-only\n", f);
        fclose(f);
    }
    shader_diagnostics_recorded = 0;
    glGenBuffers(36, uniform_buffers);
    glGenBuffers(16, vertex_buffers);
    glGenBuffers(1, &index_buffer);
    glGenVertexArrays(1, &vao);
}
void gles_draw_reset(void) {
    for (unsigned i = 0; i < num_programs; ++i) {
        if (programs[i].gl_program) glDeleteProgram(programs[i].gl_program);
        if (programs[i].vs) maxwell_free(programs[i].vs);
        if (programs[i].fs) maxwell_free(programs[i].fs);
    }
    memset(programs, 0, sizeof programs);
    num_programs = 0;
    defaults();
}
static bool safe_guest(uint64_t addr, uint64_t size) {
    // These are virtual addresses mapped by the recompiler, not arbitrary CPU
    // pointers supplied by an untrusted app. Refuse overflow/out of guest space.
    const uint64_t lo = 0x7000000000ull, hi = 0x7320000000ull;
    return addr >= lo && size && size <= hi - addr && addr < hi;
}
static int attr_kind(uint32_t f) {
    switch(f) {
    case 0x03: case 0x08: case 0x0B: case 0x0F: case 0x14: case 0x17:
    case 0x1B: case 0x20: case 0x23: case 0x27: case 0x2C: case 0x2F: return 2;
    case 0x04: case 0x09: case 0x0C: case 0x10: case 0x15: case 0x18:
    case 0x1C: case 0x21: case 0x24: case 0x28: case 0x2D: case 0x30: return 1;
    default: return 0;
    }
}
typedef struct { GLenum type; GLint components; bool normalized, integer; uint32_t bytes; } Format;
static Format vertex_format(uint32_t fmt) {
    uint32_t n = 0, bits = 0, kind = 0;
    if (fmt >= 0x01 && fmt <= 0x04) { n = 1; bits = 8; kind = fmt - 0x01; }
    else if (fmt >= 0x05 && fmt <= 0x09) { n = 1; bits = 16; kind = fmt - 0x05 + 4; }
    else if (fmt >= 0x0A && fmt <= 0x0C) { n = 1; bits = 32; kind = fmt - 0x0A + 9; }
    else if (fmt >= 0x0D && fmt <= 0x10) { n = 2; bits = 8; kind = fmt - 0x0D; }
    else if (fmt >= 0x11 && fmt <= 0x15) { n = 2; bits = 16; kind = fmt - 0x11 + 4; }
    else if (fmt >= 0x16 && fmt <= 0x18) { n = 2; bits = 32; kind = fmt - 0x16 + 9; }
    else if (fmt >= 0x19 && fmt <= 0x1C) { n = 3; bits = 8; kind = fmt - 0x19; }
    else if (fmt >= 0x1D && fmt <= 0x21) { n = 3; bits = 16; kind = fmt - 0x1D + 4; }
    else if (fmt >= 0x22 && fmt <= 0x24) { n = 3; bits = 32; kind = fmt - 0x22 + 9; }
    else if (fmt >= 0x25 && fmt <= 0x28) { n = 4; bits = 8; kind = fmt - 0x25; }
    else if (fmt >= 0x29 && fmt <= 0x2D) { n = 4; bits = 16; kind = fmt - 0x29 + 4; }
    else if (fmt >= 0x2E && fmt <= 0x30) { n = 4; bits = 32; kind = fmt - 0x2E + 9; }
    else return (Format){0};
    GLenum type = 0;
    switch(kind) {
        case 0: type = GL_UNSIGNED_BYTE; break;
        case 1: type = GL_BYTE; break;
        case 2: type = GL_UNSIGNED_BYTE; break;
        case 3: type = GL_BYTE; break;
        case 4: type = GL_HALF_FLOAT; break;
        case 5: type = GL_UNSIGNED_SHORT; break;
        case 6: type = GL_SHORT; break;
        case 7: type = GL_UNSIGNED_SHORT; break;
        case 8: type = GL_SHORT; break;
        case 9: type = GL_FLOAT; break;
        case 10: type = GL_UNSIGNED_INT; break;
        case 11: type = GL_INT; break;
    }
    return (Format){type,(GLint)n,kind==0||kind==1||kind==5||kind==6,kind==2||kind==3||
           kind==7||kind==8||kind==10||kind==11,n*bits/8};
}
static GLuint compile_shader(GLenum kind, const char *source,
                             uint64_t guest_vs, uint64_t guest_fs) {
    GLuint sh = glCreateShader(kind);
    glShaderSource(sh, 1, &source, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        if (shaders_failed < 12) {
            char log[1024] = {0};
            glGetShaderInfoLog(sh, sizeof log, NULL, log);
            fprintf(stderr, "[gles-nvn] Maxwell GLES shader failed: %s\n", log);
            shader_diagnostic(kind == GL_VERTEX_SHADER ? "vertex-compile" : "fragment-compile",
                              guest_vs, guest_fs, log);
        }
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}
static uint32_t attribute_key(void) {
    uint32_t h = 2166136261u;
    for (int i = 0; i < st.nattrib; ++i) {
        h = (h ^ (st.attrib[i] & 255u)) * 16777619u;
    }
    return h ^ (uint32_t)st.nattrib;
}
static Program *program_for_draw(void) {
    if (!st.program ||
        (st.program->stage_mask & ~((1u << STAGE_VERTEX) | (1u << STAGE_FRAGMENT))) ||
        !st.program->stages[0].code_addr ||
        !st.program->stages[1].code_addr) { rejection[R_NO_PROGRAM]++; return NULL; }
    const uint64_t vs = st.program->stages[0].code_addr, fs = st.program->stages[1].code_addr;
    uint32_t attr = attribute_key();
    for (unsigned i = 0; i < num_programs; ++i)
        if (programs[i].nvn == st.program && programs[i].vs_addr == vs &&
            programs[i].fs_addr == fs && programs[i].attr_key == attr) return &programs[i];
    if (num_programs == PROGRAM_SLOTS) { rejection[R_CACHE]++; return NULL; }
    Program *p = &programs[num_programs++];
    p->nvn = st.program; p->vs_addr = vs; p->fs_addr = fs; p->attr_key = attr;
    ShaderKey vk = {0}, fk = {0};
    vk.glsl = fk.glsl = 1;
    vk.glsl_es = fk.glsl_es = 1;
    vk.flip_y = fk.flip_y = nvn_window_origin() == 0;
    vk.depth_minus_one = nvn_depth_mode() == 0;
    for (int i = 0; i < st.nattrib; ++i)
        vk.attr_kind[i] = (uint8_t)attr_kind(st.attrib[i] & 255u);
    // Translator global variables are also used on Vulkan: GLES is a
    // mutually exclusive backend, so there is never cross-backend access.
    maxwell_gmem_base = 0x7240000000ull;
    maxwell_gmem_size = 0x00D0000000ull;
    size_t vlimit = st.program->stages[0].const_offset;
    size_t flimit = st.program->stages[1].const_offset;
    if (!vlimit || vlimit > 0x100000) vlimit = 0x10000;
    if (!flimit || flimit > 0x100000) flimit = 0x10000;
    p->vs = maxwell_translate((const uint8_t *)(uintptr_t)vs, vlimit, STAGE_VERTEX, &vk);
    if (!p->vs || !p->vs->msl) {
        shader_diagnostic("vertex-translate", vs, fs,
                          p->vs ? p->vs->error : "translator returned null");
        rejection[R_TRANSLATE]++; shaders_failed++; return p;
    }
    fk.vs_out_mask = p->vs->out_mask;
    p->fs = maxwell_translate((const uint8_t *)(uintptr_t)fs, flimit, STAGE_FRAGMENT, &fk);
    if (!p->fs || !p->fs->msl) {
        shader_diagnostic("fragment-translate", vs, fs,
                          p->fs ? p->fs->error : "translator returned null");
        rejection[R_TRANSLATE]++; shaders_failed++; return p;
    }
    // Do not issue draws with unresolved shader resources or semantics.
    // Fragment-only native 2D samplers are now supported. Vertex samplers
    // and cross-stage sampler-name conflicts still need a separate mapping.
    if (p->vs->ntex || p->fs->ntex > 32 || p->vs->uses_gmem || p->fs->uses_gmem ||
        p->vs->uses_gmem_map || p->fs->uses_gmem_map ||
        strstr(p->vs->msl, "uint64_t") || strstr(p->fs->msl, "uint64_t") ||
        strstr(p->vs->msl, "subgroup") || strstr(p->fs->msl, "subgroup")) {
        shader_diagnostic("unsupported-maxwell-feature", vs, fs,
                          p->vs->ntex || p->fs->ntex > 32 ? "unsupported shader sampler stages/count" :
                          p->vs->uses_gmem || p->fs->uses_gmem ||
                          p->vs->uses_gmem_map || p->fs->uses_gmem_map ? "global-memory pending" :
                          "GLSL ES capability pending");
        rejection[R_SHADER_FEATURE]++; shaders_failed++;
        return p;
    }
    GLuint v = compile_shader(GL_VERTEX_SHADER,p->vs->msl, vs, fs);
    GLuint f = v ? compile_shader(GL_FRAGMENT_SHADER,p->fs->msl, vs, fs) : 0;
    if (!v || !f) {
        if (v) glDeleteShader(v);
        if (f) glDeleteShader(f);
        rejection[R_COMPILE]++; shaders_failed++;
        return p;
    }
    GLuint program = glCreateProgram();
    glAttachShader(program, v); glAttachShader(program, f);
    glLinkProgram(program);
    glDeleteShader(v); glDeleteShader(f);
    GLint ok = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok) {
        if (shaders_failed < 12) {
            char log[1024] = {0};
            glGetProgramInfoLog(program, sizeof log, NULL, log);
            fprintf(stderr, "[gles-nvn] Maxwell GLES program link: %s\n", log);
            shader_diagnostic("program-link", vs, fs, log);
        }
        glDeleteProgram(program);
        rejection[R_COMPILE]++; shaders_failed++;
        return p;
    }
    p->gl_program = program;
    shaders_ok++;
    fprintf(stderr,"[gles-nvn] real Maxwell shader linked: vs=%" PRIx64 " fs=%" PRIx64
                   " attrs=%x VS_cbuf=%x FS_cbuf=%x\n",
            vs, fs, p->vs->attr_mask, p->vs->cbuf_mask, p->fs->cbuf_mask);
    return p;
}

static bool bind_uniforms(Program *p) {
    static const uint8_t zeros[65536] = {0};
    GLint max_bindings = 0;
    glGetIntegerv(GL_MAX_UNIFORM_BUFFER_BINDINGS, &max_bindings);
    GLuint binding = 0;
    for (int stage = 0; stage < 2; ++stage) {
        ShaderInfo *info = stage ? p->fs : p->vs;
        for (int k = 0; k < 18; ++k) {
            if (!(info->cbuf_mask & (1u << k))) continue;
            char name[12];
            snprintf(name,sizeof name,"%s_CB%d",stage ? "F" : "V", k);
            GLuint block = glGetUniformBlockIndex(p->gl_program, name);
            if (block == GL_INVALID_INDEX) continue;
            GLint size = 0;
            glGetActiveUniformBlockiv(p->gl_program,block,GL_UNIFORM_BLOCK_DATA_SIZE,&size);
            if (size <= 0 || size > 65536) { rejection[R_UBO]++; return false; }
            const void *src = zeros;
            uint64_t bytes = 0;
            uint32_t driver[0x800 / 4] = {0};
            if (k == 0) {
                // cbuf0 exposes NVN storage range descriptors to Maxwell,
                // including their 64-bit guest addresses. This mirrors the
                // existing Vulkan driver-constants ABI; consumers requiring
                // unsupported GMEM operations are still rejected.
                uint32_t base = stage ? 0x510 : 0x110;
                for (int i = 0; i < 16; ++i) {
                    const Range *buffer = &st.sbuf[stage][i];
                    uint32_t *word = &driver[(base + 16 * i)/4];
                    word[0] = (uint32_t)buffer->addr;
                    word[1] = (uint32_t)(buffer->addr >> 32);
                    word[2] = (uint32_t)buffer->size;
                }
                src = driver;
                bytes = sizeof driver;
            } else if (k == 1) {
                const NvnShaderStage *ss = &st.program->stages[stage];
                uint64_t addr = ss->code_addr + ss->const_offset;
                bytes = ss->const_size;
                if (safe_guest(addr, bytes)) src = (const void *)(uintptr_t)addr;
                else bytes = 0;
            } else if (k >= 3) {
                Range r = st.ubuf[stage][k-3];
                bytes = r.size;
                if (safe_guest(r.addr,r.size)) src = (const void *)(uintptr_t)r.addr;
                else bytes = 0;
            }
            // Uniform blocks shared between shader stages still need
            // their own contents. Allocate binding slots only for active
            // blocks instead of assuming >=36 ES uniform binding points.
            if (binding >= 36 || binding >= (GLuint)max_bindings) {
                rejection[R_UBO]++; return false;
            }
            uint8_t *upload = calloc(1,(size_t)size);
            if (!upload) { rejection[R_UBO]++; return false; }
            if (bytes) memcpy(upload,src,(size_t)((uint64_t)size < bytes ? (uint64_t)size : bytes));
            glBindBuffer(GL_UNIFORM_BUFFER, uniform_buffers[binding]);
            glBufferData(GL_UNIFORM_BUFFER,(GLsizeiptr)size,upload,GL_STREAM_DRAW);
            glBindBufferBase(GL_UNIFORM_BUFFER,binding,uniform_buffers[binding]);
            glUniformBlockBinding(p->gl_program,block,binding);
            binding++;
            free(upload);
        }
    }
    // The Maxwell translator adds an optional tint block for most fragment
    // outputs. Zero tint is the normal unmodified game presentation. Rejecting
    // these shaders would unnecessarily skip all ordinary solid-color passes.
    if (p->fs->uses_tint) {
        GLuint block = glGetUniformBlockIndex(p->gl_program, "Tint");
        if (block != GL_INVALID_INDEX) {
            if (binding >= 36 || binding >= (GLuint)max_bindings) return false;
            static const float no_tint[8] = {0};
            glBindBuffer(GL_UNIFORM_BUFFER, uniform_buffers[binding]);
            glBufferData(GL_UNIFORM_BUFFER, sizeof no_tint, no_tint, GL_STREAM_DRAW);
            glBindBufferBase(GL_UNIFORM_BUFFER, binding, uniform_buffers[binding]);
            glUniformBlockBinding(p->gl_program, block, binding++);
        }
    }
    // The GLES backend currently renders at native source scale (1:1).
    // Supply the corresponding identity RScale values, not Vulkan dynamic
    // resolution coefficients.
    if (p->fs->uses_rscale) {
        GLuint block = glGetUniformBlockIndex(p->gl_program, "RScale");
        if (block != GL_INVALID_INDEX) {
            if (binding >= 36 || binding >= (GLuint)max_bindings) return false;
            float identity[66*4] = {0};
            for (unsigned i = 0; i < 66; ++i) {
                identity[i*4] = 1.f;
                identity[i*4+1] = 1.f;
                identity[i*4+2] = 1.f;
                identity[i*4+3] = 1.f;
            }
            glBindBuffer(GL_UNIFORM_BUFFER, uniform_buffers[binding]);
            glBufferData(GL_UNIFORM_BUFFER, sizeof identity, identity, GL_STREAM_DRAW);
            glBindBufferBase(GL_UNIFORM_BUFFER, binding, uniform_buffers[binding]);
            glUniformBlockBinding(p->gl_program, block, binding++);
        }
    }
    return true;
}

static void normalize_swizzle(const uint8_t *src, uint8_t out[4]) {
    if (!src || !(src[0] | src[1] | src[2] | src[3])) {
        out[0]=2; out[1]=3; out[2]=4; out[3]=5;
    } else memcpy(out,src,4);
}
static bool compatible_texture_view(const NvnTexEntry *entry, uint8_t swizzle[4],
                                    int *reason) {
    const NvnTexture *tex=entry->tex;
    if (!tex) { *reason=V_UNKNOWN; return false; }
    const NvnTextureView *v=&entry->view;
    normalize_swizzle(tex->swizzle,swizzle);
    if (!entry->has_view) return true;
    // Do not reject the NVN depth-mode/target flags by treating them as
    // unrecognized bits: these bits are defined by objects.c (16 and 32).
    if (v->setmask & ~63u) { *reason=V_UNKNOWN; return false; }
    if ((v->setmask & 1u) &&
        (v->base_level != 0 ||
         (v->num_levels && v->num_levels != tex->layout.levels))) {
        // A view covering the same complete mip chain is native GLES
        // texture state and does not require a different GL view object.
        // Partial mip selections still require a separate texture view.
        *reason=V_LEVEL; return false;
    }
    if ((v->setmask & 2u) &&
        (v->min_layer != 0 ||
         (v->num_layers && v->num_layers != tex->layout.layers))) {
        *reason=V_LAYER; return false;
    }
    if ((v->setmask & 4u) && v->format != tex->format) {
        *reason=V_FORMAT; return false;
    }
    if ((v->setmask & 32u) && v->target != tex->target) {
        // A 2D slice of an array needs an actual GL texture-view object.
        *reason=V_TARGET; return false;
    }
    if ((v->setmask & 16u) && tex->format >= 0x32 &&
        tex->format <= 0x36 && v->ds_mode != tex->ds_mode) {
        *reason=V_DEPTH; return false;
    }
    if (v->setmask & 8u) normalize_swizzle(v->swizzle,swizzle);
    for (int c=0;c<4;c++) if (swizzle[c] > 5u) {
        *reason=V_UNKNOWN; return false;
    }
    // The actual channel selection is applied through the four GLES 3.2
    // GL_TEXTURE_SWIZZLE_R/G/B/A parameters, never treated as identity.
    return true;
}
static void rejected_view(const NvnTexEntry *entry, int reason) {
    if (reason < 0 || reason >= V_REASON_COUNT) reason=V_UNKNOWN;
    view_rejection_reason[reason]++;
    // Persist distinct cases in the existing runtime log, not thousands
    // of identical lines. This captures the exact blocker if more remains.
    static struct {uint32_t mask,fmt,target; int reason;} seen[24];
    static int nseen=0;
    if (!entry || !entry->has_view || !entry->tex) return;
    const NvnTextureView *v=&entry->view;
    for (int i=0;i<nseen;i++)
        if (seen[i].mask==v->setmask && seen[i].fmt==v->format &&
            seen[i].target==v->target && seen[i].reason==reason) return;
    if (nseen>=24) return;
    seen[nseen].mask=v->setmask; seen[nseen].fmt=v->format;
    seen[nseen].target=v->target; seen[nseen].reason=reason;
    nseen++;
    fprintf(stderr,"[gles-view] rejected reason=%d mask=%#x tex=%#x/"
                   "%u levels=%u layers=%u view=%#x/%u"
                   " lv=%u+%u layer=%u+%u ds=%u/%u sw=%u,%u,%u,%u\n",
            reason,v->setmask,entry->tex->format,entry->tex->target,
            entry->tex->levels,entry->tex->layout.layers,v->format,v->target,
            v->base_level,v->num_levels,v->min_layer,v->num_layers,
            v->ds_mode,entry->tex->ds_mode,
            v->swizzle[0],v->swizzle[1],v->swizzle[2],v->swizzle[3]);
}
static bool bind_textures(Program *p) {
    if (!p->fs || p->fs->ntex == 0) return true;
    GLint max_units = 0;
    glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS, &max_units);
    if (p->fs->ntex > max_units || p->fs->ntex > 32) {
        rejection[R_TEXTURE]++; texture_rejection[T_KIND]++; return false;
    }
    NvnTexture *seen_tex[32]={0};
    uint8_t seen_swizzle[32][4]={{0}};
    int bound=0;
    for (int i=0; i<p->fs->ntex; i++) {
        const ShaderTexture *ref=&p->fs->tex[i];
        bool array=ref->type == TEXTYPE_2D_ARRAY;
        if (array) texture_array_attempts++;
        if (ref->is_image || ref->bindless ||
            (ref->type != TEXTYPE_2D && !array)) {
            rejection[R_TEXTURE]++; texture_rejection[T_KIND]++; return false;
        }
        int slot=((int)ref->handle_offset-0x20)/8;
        if (slot<0 || slot>=32) {
            rejection[R_TEXTURE]++; texture_rejection[T_HANDLE]++; return false;
        }
        if (!st.tpool || !st.tpool->entries) {
            rejection[R_TEXTURE]++; texture_rejection[T_POOL]++; return false;
        }
        uint64_t handle=st.tex[STAGE_FRAGMENT][slot];
        uint32_t tic=(uint32_t)handle&0xfffffu;
        uint32_t tsc=(uint32_t)(handle>>20)&0xfffu;
        if (!handle || tic>=(uint32_t)st.tpool->count) {
            rejection[R_TEXTURE]++; texture_rejection[T_HANDLE]++; return false;
        }
        const NvnTexEntry *entry=&((const NvnTexEntry*)st.tpool->entries)[tic];
        NvnTexture *tex=entry->tex;
        if (!tex || (array ? tex->target!=4 : tex->target!=1)) {
            rejection[R_TEXTURE]++; texture_rejection[T_DESCRIPTOR]++; return false;
        }
        uint8_t swizzle[4];
        int why=V_UNKNOWN;
        if (!compatible_texture_view(entry,swizzle,&why)) {
            rejected_view(entry,why);
            rejection[R_TEXTURE]++; texture_rejection[T_VIEW]++; return false;
        }
        // A mutable GLES texture has one swizzle state for every unit.
        // If a shader samples the same NVN image with conflicting views,
        // reject rather than silently rendering the wrong channel mapping.
        bool conflict=false;
        for (int b=0;b<bound;b++)
            if (seen_tex[b]==tex && memcmp(seen_swizzle[b],swizzle,4)!=0)
                conflict=true;
        if (conflict) {
            rejected_view(entry,V_SWIZZLE_CONFLICT);
            rejection[R_TEXTURE]++; texture_rejection[T_VIEW]++; return false;
        }
        seen_tex[bound]=tex; memcpy(seen_swizzle[bound],swizzle,4); bound++;
        if (tex==st.color[0] || tex==st.depth) {
            rejection[R_TEXTURE]++; texture_rejection[T_FEEDBACK]++; return false;
        }
        NvnSamplerDesc *sampler=NULL;
        if (st.spool && st.spool->entries && tsc<(uint32_t)st.spool->count)
            sampler=&((NvnSamplerDesc*)st.spool->entries)[tsc];
        if (!gles_sample_texture(tex,sampler,i,ref->shadow,ref->type,swizzle)) {
            rejection[R_TEXTURE]++; texture_rejection[T_UPLOAD]++; return false;
        }
        if (entry->has_view) texture_views_accepted++;
        if (array) texture_array_bound++;
        char name[16];
        snprintf(name,sizeof name,"t%d",i);
        GLint loc=glGetUniformLocation(p->gl_program,name);
        if (loc>=0) glUniform1i(loc,i);
    }
    return true;
}

static bool attributes(Program *p, uint32_t last_index, uint32_t first_index,
                       uint32_t instances, uint32_t base_instance) {
    uint64_t stream_bytes[16] = {0};
    // First validate the WHOLE vertex layout. No partial GL draws when a
    // required attribute is unsupported, unbound or outside the guest range.
    for (int i = 0; i < 32; ++i) {
        if (!(p->vs->attr_mask & (1u << i))) continue;
        if (i >= 16) { rejection[R_VERTEX_FORMAT]++; return false; }
        uint32_t a = i < st.nattrib ? st.attrib[i] : 0u;
        uint32_t fmt = a & 255u, stream = (a >> 8) & 31u, off = a >> 13;
        Format f = vertex_format(fmt);
        if (!fmt || !f.type || stream >= 16 || stream >= (uint32_t)st.nstream)
            continue; // known default (0,0,0,1), not a fetched attribute
        uint32_t stride = st.stream[stream][0], divisor = st.stream[stream][1];
        Range v = st.vbuf[stream];
        if (!stride || stride > 2048 || off > 65536 || !v.addr || !v.size) {
            rejection[R_VERTEX_FORMAT]++; return false;
        }
        // NVN/Vulkan firstInstance biases the per-instance binding;
        // GLES3 lacks base-instance draw entry points, so bias its VBO
        // attribute start. The divisor still applies to local gl_InstanceID.
        uint64_t maxv = divisor ? (uint64_t)base_instance +
                                  ((uint64_t)instances - 1)/divisor : last_index;
        uint64_t need = maxv*(uint64_t)stride + off + f.bytes;
        if (need > v.size || need > 16u*1024*1024 || !safe_guest(v.addr,need)) {
            rejection[R_VERTEX_RANGE]++; return false;
        }
        if (need > stream_bytes[stream]) stream_bytes[stream] = need;
    }
    glBindVertexArray(vao);
    for (int i = 0; i < 16; ++i) glDisableVertexAttribArray((GLuint)i);
    // Upload once per stream so a later attribute cannot truncate a VBO that
    // earlier attributes read from.
    for (int stream = 0; stream < 16; ++stream) {
        if (!stream_bytes[stream]) continue;
        glBindBuffer(GL_ARRAY_BUFFER, vertex_buffers[stream]);
        glBufferData(GL_ARRAY_BUFFER,(GLsizeiptr)stream_bytes[stream],
                     (const void *)(uintptr_t)st.vbuf[stream].addr,GL_STREAM_DRAW);
    }
    for (int i = 0; i < 32; ++i) {
        if (!(p->vs->attr_mask & (1u << i))) continue;
        uint32_t a = i < st.nattrib ? st.attrib[i] : 0u;
        uint32_t fmt = a & 255u, stream = (a >> 8) & 31u, off = a >> 13;
        Format f = vertex_format(fmt);
        if (!fmt || !f.type || stream >= 16 || stream >= (uint32_t)st.nstream) {
            glVertexAttrib4f((GLuint)i,0,0,0,1);
            continue;
        }
        uint32_t stride = st.stream[stream][0], divisor = st.stream[stream][1];
        glBindBuffer(GL_ARRAY_BUFFER,vertex_buffers[stream]);
        uint64_t attr_off=(uint64_t)off +
            (divisor ? (uint64_t)base_instance*stride : 0);
        if (f.integer) glVertexAttribIPointer((GLuint)i,f.components,f.type,(GLsizei)stride,(const void *)(uintptr_t)attr_off);
        else glVertexAttribPointer((GLuint)i,f.components,f.type,f.normalized?GL_TRUE:GL_FALSE,
                                   (GLsizei)stride,(const void *)(uintptr_t)attr_off);
        glEnableVertexAttribArray((GLuint)i);
        glVertexAttribDivisor((GLuint)i,divisor);
    }
    (void)first_index;
    return true;
}
static GLenum primitive(uint32_t v) {
    switch(v) {
        case 0: return GL_POINTS;
        case 1: return GL_LINES;
        case 3: return GL_LINE_STRIP;
        case 4: return GL_TRIANGLES;
        case 5: return GL_TRIANGLE_STRIP;
        default: return 0;
    }
}
static uint32_t index_value(const uint8_t *ptr, uint32_t ty, uint32_t i) {
    if(ty==0) return ptr[i];
    if(ty==1) {uint16_t v; memcpy(&v,ptr+(size_t)i*2,2); return v;}
    uint32_t v;memcpy(&v,ptr+(size_t)i*4,4);return v;
}
static uint32_t index_max(const CmdRec *r, uint32_t count) {
    uint32_t typ=(uint32_t)r->x[1], max=0;
    const uint8_t *p=(const uint8_t *)(uintptr_t)r->x[3];
    if (typ==0) for(uint32_t i=0;i<count;i++) { if(p[i]>max) max=p[i]; }
    if (typ==1) for(uint32_t i=0;i<count;i++) {uint16_t v; memcpy(&v,p+2u*i,2); if(v>max) max=v;}
    if (typ==2) for(uint32_t i=0;i<count;i++) {uint32_t v; memcpy(&v,p+4u*i,4); if(v>max) max=v;}
    return max;
}
// NVN enum values mirror the Vulkan backend; unsupported blend factors
// are rejected instead of silently substituting GL_ONE.
static GLenum comparison(uint32_t op) {
    switch(op) {
    case 1: return GL_NEVER;
    case 2: return GL_LESS;
    case 3: return GL_EQUAL;
    case 4: return GL_LEQUAL;
    case 5: return GL_GREATER;
    case 6: return GL_NOTEQUAL;
    case 7: return GL_GEQUAL;
    case 0: case 8: return GL_ALWAYS;
    default: return 0;
    }
}
static GLenum stencil_op(uint32_t op) {
    switch(op) {
    case 0: case 1: return GL_KEEP;
    case 2: return GL_ZERO;
    case 3: return GL_REPLACE;
    case 4: return GL_INCR;
    case 5: return GL_DECR;
    case 6: return GL_INVERT;
    case 7: return GL_INCR_WRAP;
    case 8: return GL_DECR_WRAP;
    default: return 0;
    }
}
static GLenum blend_factor(uint8_t f) {
    switch (f) {
    case 1: return GL_ZERO;
    case 2: return GL_ONE;
    case 3: return GL_SRC_COLOR;
    case 4: return GL_ONE_MINUS_SRC_COLOR;
    case 5: return GL_SRC_ALPHA;
    case 6: return GL_ONE_MINUS_SRC_ALPHA;
    case 7: return GL_DST_ALPHA;
    case 8: return GL_ONE_MINUS_DST_ALPHA;
    case 9: return GL_DST_COLOR;
    case 10: return GL_ONE_MINUS_DST_COLOR;
    case 11: return GL_SRC_ALPHA_SATURATE;
    case 0x61: return GL_CONSTANT_COLOR;
    case 0x62: return GL_ONE_MINUS_CONSTANT_COLOR;
    case 0x63: return GL_CONSTANT_ALPHA;
    case 0x64: return GL_ONE_MINUS_CONSTANT_ALPHA;
    default: return 0;
    }
}
static GLenum blend_equation(uint8_t f) {
    switch (f) {
    case 1: return GL_FUNC_ADD;
    case 2: return GL_FUNC_SUBTRACT;
    case 3: return GL_FUNC_REVERSE_SUBTRACT;
    case 4: return GL_MIN;
    case 5: return GL_MAX;
    default: return 0;
    }
}
static bool bind_fixed_state(void) {
    // Alpha-to-coverage is native GLES3 state; formerly every draw enabling
    // it was rejected before the framebuffer could show any pixels.
    if (st.ms[0xC]) glEnable(GL_SAMPLE_ALPHA_TO_COVERAGE);
    else glDisable(GL_SAMPLE_ALPHA_TO_COVERAGE);
    // Coverage-to-color/modulation are NVN-specific and not equivalent
    // to alpha-to-coverage; reject them instead of pretending to render.
    if (st.ms[0xE] || st.ms[0x10]) {
        reject_fixed[FIX_MULTISAMPLE]++;return false;
    }
    if (st.poly[2] != 2) {
        reject_fixed[FIX_POLYGON]++;return false; // GLES lacks polygon-line core
    }
    glDisable(GL_CULL_FACE);
    if (st.poly[0]) {
        if (st.poly[0] > 2) {reject_fixed[FIX_POLYGON]++;return false;}
        glEnable(GL_CULL_FACE);
        glCullFace(st.poly[0] == 1 ? GL_FRONT : GL_BACK);
        bool face_ccw = (st.poly[1] == 1) != (nvn_window_origin() == 0);
        glFrontFace(face_ccw ? GL_CCW : GL_CW);
    }
    glColorMask(st.channel_mask & 1u, st.channel_mask & 2u,
                st.channel_mask & 4u, st.channel_mask & 8u);
    if (st.color_state[0] & 1u) {
        const uint8_t *b = st.blend[0];
        GLenum cs = blend_factor(b[1]), cd = blend_factor(b[2]),
               as = blend_factor(b[3]), ad = blend_factor(b[4]),
               ce = blend_equation(b[5]), ae = blend_equation(b[6]);
        if (!cs || !cd || !as || !ad || !ce || !ae) {
            reject_fixed[FIX_BLEND]++;return false;
        }
        glEnable(GL_BLEND);
        glBlendColor(st.blend_color[0], st.blend_color[1],
                     st.blend_color[2], st.blend_color[3]);
        glBlendFuncSeparate(cs, cd, as, ad);
        glBlendEquationSeparate(ce, ae);
    } else glDisable(GL_BLEND);
    // Match the Vulkan renderer: dt = st.ds[0] && pass_depth,
    // sten = st.ds[3] && pass_stencil. NVN can keep tests enabled in
    // persistent state while drawing to a color-only or depth-only target.
    // Missing attachments disable the corresponding test, not the draw.
    const bool depth_attachment=st.depth &&
        (st.depth->format>=0x32 && st.depth->format<=0x36);
    const bool stencil_attachment=st.depth &&
        (st.depth->format==0x35 || st.depth->format==0x36);
    if (st.ds[0] && depth_attachment) {
        GLenum compare=comparison(st.ds[2]);
        if (!compare) {reject_fixed[FIX_DEPTH]++;return false;}
        glEnable(GL_DEPTH_TEST);
        glDepthFunc(compare);
        glDepthMask(st.ds[1] ? GL_TRUE : GL_FALSE);
    } else {
        if (st.ds[0]) depth_without_attachment++;
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
    }
    glDepthRangef(st.depth_range[0][0], st.depth_range[0][1]);
    if (st.ds[3] && stencil_attachment) {
        uint32_t bits = st.ds[5] | st.ds[6] << 8 | st.ds[7] << 16;
        for (int face = 0; face < 2; ++face) {
            GLenum target = face ? GL_BACK : GL_FRONT;
            uint32_t op = face ? bits >> 12 : bits;
            GLenum cmp = comparison(face ? st.ds[4] >> 4 : st.ds[4] & 0xf);
            GLenum fail = stencil_op(op & 0xf), pass = stencil_op((op >> 8) & 0xf),
                   depth_fail = stencil_op((op >> 4) & 0xf);
            if (!cmp || !fail || !pass || !depth_fail) {
                reject_fixed[FIX_STENCIL]++;return false;
            }
            glStencilFuncSeparate(target, cmp, (GLint)st.stencil_ref[face],
                                  st.stencil_vmask[face]);
            glStencilOpSeparate(target, fail, depth_fail, pass);
            glStencilMaskSeparate(target, st.stencil_mask[face]);
        }
        glEnable(GL_STENCIL_TEST);
    } else {
        if (st.ds[3]) stencil_without_attachment++;
        glDisable(GL_STENCIL_TEST);
    }
    // NVN scissor state is already recorded in pixel coordinates.
    // A large default rectangle is equivalent to scissor disabled.
    if (st.scissor[0][2] < 0 || st.scissor[0][3] < 0) {
        reject_fixed[FIX_SCISSOR]++;return false;
    }
    glEnable(GL_SCISSOR_TEST);
    glScissor(st.scissor[0][0], st.scissor[0][1],
              st.scissor[0][2], st.scissor[0][3]);
    return true;
}
bool gles_draw_execute(const CmdRec *r, bool indexed) {
    attempts++;
    if (!r->x[2] || r->x[2] > 1000000) return false;
    // Preserve attachments and raster states instead of rejecting every
    // normal scene with depth, blending, culling or channel-mask state.
    if ((st.ncolor==0 && !st.depth) || st.ncolor<0 || st.ncolor>8 ||
        (st.ncolor>0 && !st.color[0])) {
        rejection[R_TARGET]++; reject_target_layout++; return false;
    }
    for(int color_index=0;color_index<st.ncolor;color_index++) {
    if (!st.color[color_index]) {
        rejection[R_TARGET]++;reject_target_layout++;return false;
    }
    if (!gles_color_target_supported(st.color[color_index]->format)) {
        rejection[R_TARGET]++;reject_target_format++;return false;
    }
    }
    GLenum prim=primitive((uint32_t)r->x[0]);
    if (!prim) { rejection[R_TOPOLOGY]++; return false; }
    uint32_t count=(uint32_t)r->x[2], first=indexed?0:(uint32_t)r->x[1];
    uint32_t instances=(uint32_t)(indexed?r->x[6]:r->x[4]);
    if (!instances) instances=1;
    if (instances>1024 || first>1000000) { rejection[R_VERTEX_RANGE]++; return false; }
    uint32_t maxindex=first+count-1;
    uint64_t first_instance_raw=indexed ? r->x[5] : r->x[3];
    if (first_instance_raw>UINT32_MAX) {
        rejected_base_instance++;rejection[R_INDICES]++;return false;
    }
    uint32_t base_instance=(uint32_t)first_instance_raw;
    GLenum index_type=0;
    int32_t base_vertex = indexed ? (int32_t)r->x[4] : 0;
    if (indexed) {
        uint32_t ty=(uint32_t)r->x[1];
        uint64_t bytes = (uint64_t)count*(ty==0?1u:ty==1?2u:4u);
        if (ty>2 || !safe_guest(r->x[3],bytes)) {
            rejection[R_INDICES]++; return false;
        }
        index_type=ty==0?GL_UNSIGNED_BYTE:ty==1?GL_UNSIGNED_SHORT:GL_UNSIGNED_INT;
        if(base_vertex){
            const uint8_t *src=(const uint8_t *)(uintptr_t)r->x[3];
            maxindex=0;
            // CPU-side vertex rebasing is a native ES3.2-compatible
            // equivalent of Vulkan vkCmdDrawIndexed(baseVertex).
            for(uint32_t i=0;i<count;i++){
                int64_t index=(int64_t)index_value(src,ty,i)+base_vertex;
                if(index<0 || index>UINT32_MAX) {
                    rejection[R_INDICES]++;return false;
                }
                if((uint64_t)index>maxindex) maxindex=(uint32_t)index;
            }
        } else maxindex=index_max(r,count);
    }
    Program *p=program_for_draw();
    if (!p || !p->gl_program) return false;
    int w=0,h=0;
    // The upload path can create temporary FBOs. Bind the real render
    // target AFTER binding sampled images, not before.
    glUseProgram(p->gl_program);
    if (!bind_textures(p)) return false;
    if (!gles_draw_framebuffer(st.color, st.ncolor, st.depth, &w,&h)) {
        rejection[R_TARGET]++;reject_target_fbo++;return false;
    }
    glViewport((GLint)st.viewport[0][0],(GLint)st.viewport[0][1],
               (GLsizei)st.viewport[0][2],(GLsizei)st.viewport[0][3]);
    if (!bind_fixed_state()) { rejection[R_DEPTH_BLEND]++; return false; }
    glUseProgram(p->gl_program);
    // The GLES shader prelude accounts for NVN firstInstance in the
    // Vulkan-style gl_InstanceIndex; gl_InstanceID itself still starts at 0.
    GLint base_uniform=glGetUniformLocation(p->gl_program,"gles_base_instance");
    if(base_uniform>=0) glUniform1ui(base_uniform,base_instance);
    if (!bind_uniforms(p) ||
        !attributes(p,maxindex,first,instances,base_instance)) return false;
    if (indexed) {
        const void *upload=(const void *)(uintptr_t)r->x[3];
        uint32_t *rebased=NULL;
        if(base_vertex){
            rebased=malloc((size_t)count*sizeof *rebased);
            if(!rebased){rejection[R_INDICES]++;return false;}
            const uint8_t *src=(const uint8_t *)(uintptr_t)r->x[3];
            uint32_t ty=(uint32_t)r->x[1];
            for(uint32_t i=0;i<count;i++)
                rebased[i]=(uint32_t)((int64_t)index_value(src,ty,i)+base_vertex);
            upload=rebased;
            index_type=GL_UNSIGNED_INT;
        }
        GLsizeiptr n=(GLsizeiptr)((uint64_t)count*(index_type==GL_UNSIGNED_BYTE?1u:index_type==GL_UNSIGNED_SHORT?2u:4u));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,index_buffer);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,n,upload,GL_STREAM_DRAW);
        free(rebased);
        if (instances==1) glDrawElements(prim,(GLsizei)count,index_type,0);
        else glDrawElementsInstanced(prim,(GLsizei)count,index_type,0,(GLsizei)instances);
        if(base_vertex) rebased_index_draws++;
    } else {
        if (instances==1) glDrawArrays(prim,(GLint)first,(GLsizei)count);
        else glDrawArraysInstanced(prim,(GLint)first,(GLsizei)count,(GLsizei)instances);
    }
    // Earlier logs called every glDraw "ok" without checking the driver.
    // Sample GL errors at startup and periodically so a rejected draw is
    // not mistaken for correctly rendered pixels. No per-draw readbacks.
    const bool check_driver = attempts <= 128 || (attempts % 256 == 0);
    if (check_driver) {
        checked_draws++;
        last_gl_draw_error = glGetError();
        if (last_gl_draw_error != GL_NO_ERROR) {
            gl_draw_errors++;
            if (gl_draw_errors <= 16)
                fprintf(stderr,
                        "[gles-nvn] draw rejected by GL driver: error=%#x"
                        " program=%u rt_fmt=%#x count=%u\n",
                        last_gl_draw_error, p->gl_program,
                        st.color[0] ? st.color[0]->format : 0, count);
            return false;
        }
    }
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    for(int i=0;i<st.ncolor;i++) gles_mark_texture_written(st.color[i]);
    if (st.ds[0] || st.ds[3]) gles_mark_texture_written(st.depth);
    if(st.ncolor>1) mrt_draws++;
    if(base_instance) {
        if(indexed) indexed_base_instance_draws++;
        else arrays_base_instance_draws++;
    }
    native_draws++;
    if (native_draws <= 12) fprintf(stderr, "[gles-nvn] GLES NVN draw issued: primitive=%u count=%u program=%u\n",
                  (unsigned)r->x[0],count,p->gl_program);
    return true;
}
bool gles_draw_state(const CmdRec *r) {
    switch(r->op) {
        case CMD_BIND_PROGRAM: st.program=(NvnProgram *)(uintptr_t)r->x[0]; return true;
        case CMD_BIND_BLEND: {
            const uint8_t *b = r->extra;
            memcpy(st.blend[b[0] & 7], b, 8);
            return true;
        }
        case CMD_BIND_MULTISAMPLE: memcpy(st.ms, r->extra, 0x18); return true;
        case CMD_BIND_CHANNEL_MASK: memcpy(&st.channel_mask,r->extra,4); return true;
        case CMD_BIND_COLOR: memcpy(st.color_state,r->extra,4); return true;
        case CMD_BIND_DEPTH_STENCIL: memcpy(st.ds,r->extra,8); return true;
        case CMD_BIND_POLYGON: memcpy(st.poly,r->extra,4); return true;
        case CMD_BIND_VERTEX_ATTRIB:
            st.nattrib=r->x[0]<16?(int)r->x[0]:16;
            memcpy(st.attrib,r->extra,(size_t)st.nattrib*4); return true;
        case CMD_BIND_VERTEX_STREAM:
            st.nstream=r->x[0]<16?(int)r->x[0]:16;
            memcpy(st.stream,r->extra,(size_t)st.nstream*8); return true;
        case CMD_BIND_VERTEX_BUFFERS:
            for(uint64_t i=0;i<r->x[1]&&i+r->x[0]<16;i++)
                memcpy(&st.vbuf[r->x[0]+i],r->extra+i*16,16);
            return true;
        case CMD_BIND_UNIFORM_BUFFERS:
            for(uint64_t i=0;i<r->x[2]&&i+r->x[1]<18&&r->x[0]<6;i++)
                memcpy(&st.ubuf[r->x[0]][r->x[1]+i],r->extra+i*16,16);
            return true;
        case CMD_BIND_STORAGE_BUFFERS:
            for(uint64_t i=0;i<r->x[2]&&i+r->x[1]<16&&r->x[0]<6;i++)
                memcpy(&st.sbuf[r->x[0]][r->x[1]+i],r->extra+i*16,16);
            return true;
        case CMD_SET_RENDER_TARGETS: {
            struct { uint64_t tex[8]; NvnTextureView views[8]; uint8_t has_view[8];
                     uint64_t depth; NvnTextureView dview; uint8_t has_dview; } *rt=(void *)r->extra;
            st.ncolor=(int)(r->x[0]>8?8:r->x[0]);
            for(int i=0;i<8;i++) st.color[i]=i<st.ncolor?(NvnTexture *)(uintptr_t)rt->tex[i]:NULL;
            st.depth=(NvnTexture *)(uintptr_t)rt->depth;
            return true;
        }
        case CMD_SET_VIEWPORTS:
            for(uint64_t i=0;i<r->x[1]&&i+r->x[0]<16;i++)
                memcpy(st.viewport[r->x[0]+i],r->extra+i*16,16);
            return true;
        case CMD_SET_SCISSORS:
            for(uint64_t i=0;i<r->x[1]&&i+r->x[0]<16;i++)
                memcpy(st.scissor[r->x[0]+i],r->extra+i*16,16);
            return true;
        case CMD_SET_DEPTH_RANGES:
            for(uint64_t i=0;i<r->x[1]&&i+r->x[0]<16;i++)
                memcpy(st.depth_range[r->x[0]+i],r->extra+i*8,8);
            return true;
        case CMD_SET_BLEND_COLOR:
            memcpy(st.blend_color, r->extra, 16);
            return true;
        case CMD_SET_STENCIL:
            for (int i = 0; i < 2; ++i) if (r->x[0] & (1u << i)) {
                if (r->x[6] == 0) st.stencil_ref[i] = (uint32_t)r->x[1];
                else if (r->x[6] == 1) st.stencil_mask[i] = (uint32_t)r->x[1];
                else st.stencil_vmask[i] = (uint32_t)r->x[1];
            }
            return true;
        case CMD_BIND_TEXTURES:
            for(uint64_t i=0;i<r->x[2] && i+r->x[1]<32 && r->x[0]<6;i++)
                memcpy(&st.tex[r->x[0]][r->x[1]+i],r->extra+i*8,8);
            return true;
        case CMD_SET_TEXTURE_POOL:
            st.tpool=(NvnDescPool *)(uintptr_t)r->x[0]; return true;
        case CMD_SET_SAMPLER_POOL:
            st.spool=(NvnDescPool *)(uintptr_t)r->x[0]; return true;
        default: return false;
    }
}
