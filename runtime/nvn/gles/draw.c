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

extern bool gles_draw_framebuffer(NvnTexture *tex, int *w, int *h);
extern uint32_t nvn_window_origin(void);
extern uint32_t nvn_depth_mode(void);

typedef struct { uint64_t addr, size; } Range;
typedef struct {
    NvnProgram *program;
    NvnTexture *color[8], *depth;
    int ncolor, nattrib, nstream;
    uint32_t attrib[16], stream[16][2];
    Range vbuf[16], ubuf[6][18], sbuf[6][16];
    float viewport[16][4];
    int32_t scissor[16][4];
    uint8_t ds[8], poly[4], color_state[4];
    uint32_t channel_mask;
} DrawState;
static DrawState st;
static GLuint uniform_buffers[36], vertex_buffers[16], index_buffer, vao;
static uint64_t native_draws, shaders_ok, shaders_failed, rejection[12];
enum { R_NO_PROGRAM, R_TARGET, R_SHADER_FEATURE, R_TRANSLATE, R_COMPILE, R_TOPOLOGY,
       R_INDICES, R_VERTEX_FORMAT, R_VERTEX_RANGE, R_UBO, R_DEPTH_BLEND, R_CACHE };
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

uint64_t gles_draw_native_count(void) { return native_draws; }
uint64_t gles_draw_program_count(void) { return shaders_ok; }
uint64_t gles_draw_shader_failure_count(void) { return shaders_failed; }
const char *gles_draw_rejection_stats(void) {
    static char buffer[640];
    snprintf(buffer, sizeof buffer,
        "maxwell_draw_attempts=%" PRIu64 "\n"
        "rejected_no_program=%" PRIu64 "\nrejected_target=%" PRIu64
        "\nrejected_shader_feature=%" PRIu64 "\nrejected_translation=%" PRIu64
        "\nrejected_compilation=%" PRIu64 "\nrejected_topology=%" PRIu64
        "\nrejected_indices=%" PRIu64 "\nrejected_vertex_format=%" PRIu64
        "\nrejected_vertex_range=%" PRIu64 "\nrejected_ubo=%" PRIu64
        "\nrejected_depth_blend=%" PRIu64 "\nrejected_cache=%" PRIu64 "\n",
        attempts, rejection[R_NO_PROGRAM], rejection[R_TARGET],
        rejection[R_SHADER_FEATURE], rejection[R_TRANSLATE],
        rejection[R_COMPILE], rejection[R_TOPOLOGY], rejection[R_INDICES],
        rejection[R_VERTEX_FORMAT], rejection[R_VERTEX_RANGE],
        rejection[R_UBO], rejection[R_DEPTH_BLEND], rejection[R_CACHE]);
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
}
void gles_draw_init(void) {
    defaults();
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
static GLuint compile_shader(GLenum kind, const char *source) {
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
    if (!p->vs || !p->vs->msl) { rejection[R_TRANSLATE]++; shaders_failed++; return p; }
    fk.vs_out_mask = p->vs->out_mask;
    p->fs = maxwell_translate((const uint8_t *)(uintptr_t)fs, flimit, STAGE_FRAGMENT, &fk);
    if (!p->fs || !p->fs->msl) { rejection[R_TRANSLATE]++; shaders_failed++; return p; }
    // Do not issue draws with unresolved shader resources or semantics.
    if (p->vs->ntex || p->fs->ntex || p->vs->uses_gmem || p->fs->uses_gmem ||
        p->vs->uses_gmem_map || p->fs->uses_gmem_map ||
        strstr(p->vs->msl, "uint64_t") || strstr(p->fs->msl, "uint64_t") ||
        strstr(p->vs->msl, "subgroup") || strstr(p->fs->msl, "subgroup")) {
        rejection[R_SHADER_FEATURE]++; shaders_failed++;
        return p;
    }
    GLuint v = compile_shader(GL_VERTEX_SHADER,p->vs->msl);
    GLuint f = v ? compile_shader(GL_FRAGMENT_SHADER,p->fs->msl) : 0;
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
static bool attributes(Program *p, uint32_t last_index, uint32_t first_index, uint32_t instances) {
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
        uint64_t maxv = divisor ? ((uint64_t)instances - 1)/divisor : last_index;
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
        if (f.integer) glVertexAttribIPointer((GLuint)i,f.components,f.type,(GLsizei)stride,(const void *)(uintptr_t)off);
        else glVertexAttribPointer((GLuint)i,f.components,f.type,f.normalized?GL_TRUE:GL_FALSE,
                                   (GLsizei)stride,(const void *)(uintptr_t)off);
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
static uint32_t index_max(const CmdRec *r, uint32_t count) {
    uint32_t typ=(uint32_t)r->x[1], max=0;
    const uint8_t *p=(const uint8_t *)(uintptr_t)r->x[3];
    if (typ==0) for(uint32_t i=0;i<count;i++) { if(p[i]>max) max=p[i]; }
    if (typ==1) for(uint32_t i=0;i<count;i++) {uint16_t v; memcpy(&v,p+2u*i,2); if(v>max) max=v;}
    if (typ==2) for(uint32_t i=0;i<count;i++) {uint32_t v; memcpy(&v,p+4u*i,4); if(v>max) max=v;}
    return max;
}
bool gles_draw_execute(const CmdRec *r, bool indexed) {
    attempts++;
    if (!r->x[2] || r->x[2] > 1000000) return false;
    if (!st.color[0] || st.ncolor != 1 || st.depth || st.ds[0] ||
        (st.color_state[0] & 1) || st.channel_mask != 0xffffffffu ||
        st.poly[0] || st.poly[2] != 2) {
        rejection[R_DEPTH_BLEND]++; return false;
    }
    GLenum prim=primitive((uint32_t)r->x[0]);
    if (!prim) { rejection[R_TOPOLOGY]++; return false; }
    uint32_t count=(uint32_t)r->x[2], first=indexed?0:(uint32_t)r->x[1];
    uint32_t instances=(uint32_t)(indexed?r->x[6]:r->x[4]);
    if (!instances) instances=1;
    if (instances>1024 || first>1000000) { rejection[R_VERTEX_RANGE]++; return false; }
    uint32_t maxindex=first+count-1;
    GLenum index_type=0;
    if (indexed) {
        uint32_t ty=(uint32_t)r->x[1];
        uint64_t bytes = (uint64_t)count*(ty==0?1u:ty==1?2u:4u);
        if (ty>2 || !safe_guest(r->x[3],bytes) || r->x[4] || r->x[5]) {
            rejection[R_INDICES]++; return false;
        }
        index_type=ty==0?GL_UNSIGNED_BYTE:ty==1?GL_UNSIGNED_SHORT:GL_UNSIGNED_INT;
        maxindex=index_max(r,count);
    } else if (r->x[3]) {
        // gl_InstanceID has no native base-instance adjustment in ES3.2.
        rejection[R_INDICES]++; return false;
    }
    Program *p=program_for_draw();
    if (!p || !p->gl_program) return false;
    int w=0,h=0;
    if (!gles_draw_framebuffer(st.color[0], &w,&h)) { rejection[R_TARGET]++; return false; }
    glViewport((GLint)st.viewport[0][0],(GLint)st.viewport[0][1],
               (GLsizei)st.viewport[0][2],(GLsizei)st.viewport[0][3]);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_STENCIL_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glUseProgram(p->gl_program);
    if (!bind_uniforms(p) || !attributes(p,maxindex,first,instances)) return false;
    if (indexed) {
        GLsizeiptr n=(GLsizeiptr)((uint64_t)count*(index_type==GL_UNSIGNED_BYTE?1u:index_type==GL_UNSIGNED_SHORT?2u:4u));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,index_buffer);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,n,(const void *)(uintptr_t)r->x[3],GL_STREAM_DRAW);
        if (instances==1) glDrawElements(prim,(GLsizei)count,index_type,0);
        else glDrawElementsInstanced(prim,(GLsizei)count,index_type,0,(GLsizei)instances);
    } else {
        if (instances==1) glDrawArrays(prim,(GLint)first,(GLsizei)count);
        else glDrawArraysInstanced(prim,(GLint)first,(GLsizei)count,(GLsizei)instances);
    }
    native_draws++;
    if (native_draws <= 12) fprintf(stderr, "[gles-nvn] real NVN draw ok: primitive=%u count=%u program=%u\n",
                  (unsigned)r->x[0],count,p->gl_program);
    return true;
}
bool gles_draw_state(const CmdRec *r) {
    switch(r->op) {
        case CMD_BIND_PROGRAM: st.program=(NvnProgram *)(uintptr_t)r->x[0]; return true;
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
        case CMD_BIND_TEXTURES: case CMD_SET_TEXTURE_POOL: case CMD_SET_SAMPLER_POOL:
            // Recorded by NVN, but not consumed by the non-textured subset.
            return true;
        default: return false;
    }
}
