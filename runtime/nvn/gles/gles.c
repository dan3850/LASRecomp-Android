// Independent LASRecomp GLES backend. Supports a strict Maxwell graphics
// subset with native GLSL ES draws, Tegra texture upload, FBO render targets,
// colour/depth clears and GPU texture blits. Unsupported operations remain
// explicitly rejected; no PixelCopy or Vulkan execution in GLES mode.
#include "gles.h"
#include "draw.h"
#include "../astc.h"
#include "../bcn_decode.h"
#include "../tegra.h"
#include <GLES3/gl3.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "../../platform.h"

typedef struct {
    GLuint color, framebuffer;
    GLsizei width, height;
    GLenum attachment;
    GLuint depth_bound;
    bool cpu_uploaded, gpu_written;
    uint64_t cpu_hash, last_cpu_check_frame;
} GlesTexture;

static SDL_Window *g_window;
static SDL_GLContext g_context;
static GLuint g_present_program, g_vertex_array;
static GLint g_present_sampler;
static NvnTexture *g_color[8], *g_depth;
static GLint g_clear_scissor[4] = {0, 0, 16384, 16384};
static bool g_draw_needs_reset;
static uint64_t g_frames, g_clears, g_draws_unsupported, g_dispatch_unsupported, g_unsupported;
static int g_last_unsupported = -1;
static uint64_t g_sample_ok, g_sample_fail, g_sample_uploaded_bytes, g_sample_cached;
static uint64_t g_copies_attempted, g_copies_succeeded, g_copies_failed;
static uint64_t g_present_missing, g_present_written, g_present_unwritten, g_present_gl_errors;
static uint32_t g_last_present_id, g_last_present_format, g_last_present_gl_error;
static GLuint g_texture_samplers[32];
enum { GLES_VIDEO_QUEUE = 8 };
typedef struct {
    NvnTexture *tex;
    uint8_t *pixels;
    uint32_t w, h;
} PendingVideo;
static PendingVideo video_queue[GLES_VIDEO_QUEUE];
static pthread_mutex_t video_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic uint64_t video_queued, video_uploaded, video_dropped;
static char g_stats[640];
static uint64_t g_executed_lists, g_last_checkpoint;

bool gles_selected(void) {
    const char *name = getenv("LARECOMP_RENDERER");
    return name && strcmp(name, "gles") == 0;
}

static void report(void) {
    mkdir("graphics", 0755);
    FILE *f = fopen("graphics/gles.txt", "w");
    if (!f) return;
    fprintf(f, "backend=opengles\nNVN_renderer=OpenGL_ES\nVulkan_initialized=0\n");
    fprintf(f, "native_maxwell_draws=%" PRIu64 "\ngles_programs_linked=%" PRIu64
               "\ngles_programs_failed=%" PRIu64 "\n",
            gles_draw_native_count(), gles_draw_program_count(), gles_draw_shader_failure_count());
    fprintf(f, "%s", gles_draw_rejection_stats());
    fprintf(f, "nvn_lists_executed=%" PRIu64 "\n", g_executed_lists);
    fprintf(f, "video_frames_queued=%" PRIu64 "\nvideo_frames_uploaded=%" PRIu64
               "\nvideo_frames_dropped=%" PRIu64 "\n",
            video_queued, video_uploaded, video_dropped);
    fprintf(f, "copy_attempted=%" PRIu64 "\ncopy_succeeded=%" PRIu64
               "\ncopy_failed=%" PRIu64 "\n", g_copies_attempted,
            g_copies_succeeded, g_copies_failed);
    fprintf(f, "present_missing=%" PRIu64 "\npresent_written=%" PRIu64
               "\npresent_unwritten=%" PRIu64 "\npresent_gl_errors=%" PRIu64
               "\nlast_present_id=%u\nlast_present_format=%#x\nlast_present_gl_error=%#x\n",
            g_present_missing, g_present_written, g_present_unwritten,
            g_present_gl_errors, g_last_present_id, g_last_present_format,
            g_last_present_gl_error);
    fprintf(f, "sample_ok=%" PRIu64 "\nsample_failed=%" PRIu64
               "\nsample_cached=%" PRIu64 "\nsample_uploaded_bytes=%" PRIu64 "\n",
            g_sample_ok, g_sample_fail, g_sample_cached, g_sample_uploaded_bytes);
    fprintf(f, "frames=%" PRIu64 "\nclears=%" PRIu64 "\nunsupported_draws=%" PRIu64
               "\nunsupported_dispatches=%" PRIu64 "\nunsupported_commands=%" PRIu64
               "\nlast_unsupported_opcode=%d\n",
            g_frames, g_clears, g_draws_unsupported, g_dispatch_unsupported,
            g_unsupported, g_last_unsupported);
    if (g_context && SDL_GL_GetCurrentContext() == g_context) {
        fprintf(f, "vendor=%s\nrenderer=%s\nversion=%s\n",
                (const char *)glGetString(GL_VENDOR), (const char *)glGetString(GL_RENDERER),
                (const char *)glGetString(GL_VERSION));
    }
    fclose(f);
}
const char *gles_stats(void) {
    snprintf(g_stats, sizeof g_stats, "GLES frames=%" PRIu64 " clears=%" PRIu64
             " nativeNVN=%" PRIu64 " programs=%" PRIu64 " failed=%" PRIu64
             " sample_ok=%" PRIu64 " sample_fail=%" PRIu64 " sample_MB=%.1f"
             " video_uploaded=%" PRIu64 " video_dropped=%" PRIu64
             " copies=%" PRIu64 "/%" PRIu64 " present_written=%" PRIu64
             " present_missing=%" PRIu64 " skipped_draws=%" PRIu64 " skipped_compute=%" PRIu64 " [%s]",
             g_frames, g_clears, gles_draw_native_count(), gles_draw_program_count(),
             gles_draw_shader_failure_count(), g_sample_ok, g_sample_fail,
             (double)g_sample_uploaded_bytes / 1048576.0,
             (uint64_t)video_uploaded, (uint64_t)video_dropped,
             g_copies_succeeded, g_copies_attempted, g_present_written,
             g_present_missing, g_draws_unsupported, g_dispatch_unsupported,
             gles_draw_rejection_summary());
    return g_stats;
}
uint64_t gles_frame_count(void) { return g_frames; }

static GLuint shader(GLenum stage, const char *source) {
    GLuint id = glCreateShader(stage);
    glShaderSource(id, 1, &source, NULL);
    glCompileShader(id);
    GLint compiled = 0;
    glGetShaderiv(id, GL_COMPILE_STATUS, &compiled);
    if (!compiled) {
        char log[1024] = {0};
        glGetShaderInfoLog(id, sizeof log, NULL, log);
        LOG("[gles] shader compilation failed: %s\n", log);
        glDeleteShader(id);
        return 0;
    }
    return id;
}

void gles_init(SDL_Window *window) {
    if (g_context) return;
    g_window = window;
    g_context = SDL_GL_CreateContext(window);
    if (!g_context) FATAL("[gles] SDL_GL_CreateContext: %s\n", SDL_GetError());
    if (!SDL_GL_MakeCurrent(window, g_context))
        FATAL("[gles] SDL_GL_MakeCurrent: %s\n", SDL_GetError());
    SDL_GL_SetSwapInterval(1);
    const char *vertex =
        "#version 300 es\n"
        "out vec2 uv;\n"
        "void main() {\n"
        "vec2 p = vec2(gl_VertexID == 1 ? 3.0 : -1.0, gl_VertexID == 2 ? 3.0 : -1.0);\n"
        "uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0);\n"
        "}\n";
    const char *fragment =
        "#version 300 es\nprecision mediump float;\n"
        "in vec2 uv; uniform sampler2D image0; out vec4 color0;\n"
        "void main() { color0 = texture(image0, uv); }\n";
    GLuint vs = shader(GL_VERTEX_SHADER, vertex), fs = shader(GL_FRAGMENT_SHADER, fragment);
    if (!vs || !fs) FATAL("[gles] presentation shader unavailable\n");
    g_present_program = glCreateProgram();
    glAttachShader(g_present_program, vs);
    glAttachShader(g_present_program, fs);
    glLinkProgram(g_present_program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    GLint linked = 0;
    glGetProgramiv(g_present_program, GL_LINK_STATUS, &linked);
    if (!linked) FATAL("[gles] presentation program link failed\n");
    g_present_sampler = glGetUniformLocation(g_present_program, "image0");
    glGenVertexArrays(1, &g_vertex_array);
    glGenSamplers(32, g_texture_samplers);
    gles_draw_init();
    LOG("[gles] genuine GLES backend: %s / %s, version %s\n",
        glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION));
    report();
}

// A real NVN image must keep its data format. A depth/stencil texture is
// not interchangeable with RGBA8, even when only used as an attachment.
typedef struct {
    GLenum internal, format, type, attachment;
} FormatGL;
static FormatGL gpu_format(uint32_t format) {
    switch (format) {
    case 0x01: return (FormatGL){GL_R8, GL_RED, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x02: return (FormatGL){GL_R8_SNORM, GL_RED, GL_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x0D: return (FormatGL){GL_RG8, GL_RG, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x0E: return (FormatGL){GL_RG8_SNORM, GL_RG, GL_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x19: case 0x25: case 0x6D: 
    case 0x41: case 0x42: case 0x43: case 0x44: case 0x4D:
    case 0x79: case 0x7A: case 0x7B: case 0x7C: case 0x7D:
    case 0x7E: case 0x7F: case 0x80: case 0x81: case 0x82:
    case 0x83: case 0x84: case 0x85: case 0x86:
        return (FormatGL){GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x4F: case 0x50:
    case 0x29: case 0x71:
        return (FormatGL){GL_RGBA16F, GL_RGBA, GL_HALF_FLOAT, GL_COLOR_ATTACHMENT0};
    case 0x2E: case 0x76:
        return (FormatGL){GL_RGBA32F, GL_RGBA, GL_FLOAT, GL_COLOR_ATTACHMENT0};
    case 0x45: case 0x46: case 0x47: case 0x48: case 0x4E:
    case 0x87: case 0x88: case 0x89: case 0x8A: case 0x8B:
    case 0x8C: case 0x8D: case 0x8E: case 0x8F: case 0x90:
    case 0x91: case 0x92: case 0x93: case 0x94:
    case 0x37: case 0x38:
        return (FormatGL){GL_SRGB8_ALPHA8, GL_RGBA, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x49: return (FormatGL){GL_R8, GL_RED, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x4A: return (FormatGL){GL_R8_SNORM, GL_RED, GL_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x4B: return (FormatGL){GL_RG8, GL_RG, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x4C: return (FormatGL){GL_RG8_SNORM, GL_RG, GL_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x3F:
        return (FormatGL){GL_R11F_G11F_B10F, GL_RGB, GL_UNSIGNED_INT_10F_11F_11F_REV, GL_COLOR_ATTACHMENT0};
    case 0x32:
        return (FormatGL){GL_DEPTH_COMPONENT16, GL_DEPTH_COMPONENT, GL_UNSIGNED_SHORT, GL_DEPTH_ATTACHMENT};
    case 0x33: case 0x34:
        return (FormatGL){GL_DEPTH_COMPONENT32F, GL_DEPTH_COMPONENT, GL_FLOAT, GL_DEPTH_ATTACHMENT};
    case 0x35:
        return (FormatGL){GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8, GL_DEPTH_STENCIL_ATTACHMENT};
    case 0x36:
        return (FormatGL){GL_DEPTH32F_STENCIL8, GL_DEPTH_STENCIL, GL_FLOAT_32_UNSIGNED_INT_24_8_REV,
                          GL_DEPTH_STENCIL_ATTACHMENT};
    default: return (FormatGL){0};
    }
}
static GlesTexture *texture(NvnTexture *tex) {
    if (!tex || !tex->width || !tex->height || tex->width > 8192 || tex->height > 8192 ||
        tex->depth > 1 || tex->samples > 1)
        return NULL;
    if (tex->backend) return tex->backend;
    FormatGL f = gpu_format(tex->format);
    if (!f.internal) {
        static uint32_t warned[256];
        if (tex->format < 256 && warned[tex->format]++ < 3)
            LOG("[gles] unsupported native texture format %#x (no RGBA fallback)\n", tex->format);
        return NULL;
    }
    GlesTexture *t = calloc(1, sizeof *t);
    if (!t) return NULL;
    t->width = (GLsizei)tex->width;
    t->height = (GLsizei)tex->height;
    t->attachment = f.attachment;
    glGenTextures(1, &t->color);
    glBindTexture(GL_TEXTURE_2D, t->color);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, (GLint)f.internal, t->width, t->height,
                 0, f.format, f.type, NULL);
    glGenFramebuffers(1, &t->framebuffer);
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER, f.attachment, GL_TEXTURE_2D, t->color, 0);
    if (f.attachment != GL_COLOR_ATTACHMENT0) {
        GLenum none = GL_NONE;
        glDrawBuffers(1, &none);
        glReadBuffer(GL_NONE);
    }
    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        // Some valid sampled formats (e.g. SNORM) are not color-renderable.
        // Keep the native GL texture for sampling, but never use it as an FBO.
        static int warned;
        if (warned++ < 15)
            LOG("[gles] no native framebuffer for fmt=%#x size=%ux%u gl=%#x (sampling retained)\n",
                tex->format, tex->width, tex->height, status);
        glDeleteFramebuffers(1, &t->framebuffer);
        t->framebuffer = 0;
    }
    tex->backend = t;
    return t;
}

// Defined below. Called by depth clearing before its implementation.
void gles_mark_texture_written(NvnTexture *tex);
bool gles_draw_framebuffer(NvnTexture *color, NvnTexture *depth, int *w, int *h) {
    GlesTexture *t = color ? texture(color) : NULL;
    if (!color && depth) {
        // Depth-only pre-passes do not have a color attachment.
        GlesTexture *z = texture(depth);
        if (!z || !z->framebuffer || z->attachment == GL_COLOR_ATTACHMENT0) return false;
        glBindFramebuffer(GL_FRAMEBUFFER, z->framebuffer);
        if (w) *w = z->width;
        if (h) *h = z->height;
        return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    }
    if (!t || !t->framebuffer || t->attachment != GL_COLOR_ATTACHMENT0) return false;
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    if (depth) {
        GlesTexture *z = texture(depth);
        if (!z || z->attachment == GL_COLOR_ATTACHMENT0 ||
            z->width != t->width || z->height != t->height) return false;
        // Creating depth textures binds their own framebuffer; restore
        // the color framebuffer before modifying its attachments.
        glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
        if (t->depth_bound != z->color) {
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
                                   GL_TEXTURE_2D, 0, 0);
            glFramebufferTexture2D(GL_FRAMEBUFFER, z->attachment,
                                   GL_TEXTURE_2D, z->color, 0);
            t->depth_bound = z->color;
        }
    } else if (t->depth_bound) {
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
                               GL_TEXTURE_2D, 0, 0);
        t->depth_bound = 0;
    }
    if (w) *w = t->width;
    if (h) *h = t->height;
    return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

// NVN ClearDepthStencil targets its own depth attachment, even when the
// currently bound color image has a different size or format.
bool gles_clear_depth(NvnTexture *depth, bool clear_depth, float value,
                      bool clear_stencil, uint32_t stencil, uint32_t mask) {
    GlesTexture *z = texture(depth);
    if (!z || !z->framebuffer || z->attachment == GL_COLOR_ATTACHMENT0) return false;
    glBindFramebuffer(GL_FRAMEBUFFER, z->framebuffer);
    glEnable(GL_SCISSOR_TEST);
    glScissor(g_clear_scissor[0], g_clear_scissor[1],
              g_clear_scissor[2], g_clear_scissor[3]);
    GLbitfield bits = 0;
    if (clear_depth) {
        glDepthMask(GL_TRUE);
        glClearDepthf(value);
        bits |= GL_DEPTH_BUFFER_BIT;
    }
    if (clear_stencil && z->attachment == GL_DEPTH_STENCIL_ATTACHMENT) {
        glStencilMask(mask);
        glClearStencil((GLint)stencil);
        bits |= GL_STENCIL_BUFFER_BIT;
    }
    if (bits) { glClear(bits); gles_mark_texture_written(depth); }
    glStencilMask(0xFF);
    glDepthMask(GL_TRUE);
    return bits != 0;
}


// Only 2D, single-slice images with a genuine CPU backing are uploaded in
// this initial native sampling path. Output data comes from Tegra layouts,
// not from fake uniform colors or a Vulkan fallback.
static unsigned bcn_type(uint32_t fmt) {
    switch (fmt) {
    case 0x41: case 0x42: case 0x45: case 0x46: return LAS_BC1;
    case 0x43: case 0x47: return LAS_BC2;
    case 0x44: case 0x48: return LAS_BC3;
    case 0x49: return LAS_BC4U;
    case 0x4A: return LAS_BC4S;
    case 0x4B: return LAS_BC5U;
    case 0x4C: return LAS_BC5S;
    case 0x4D: case 0x4E: return LAS_BC7;
    case 0x4F: return LAS_BC6S;
    case 0x50: return LAS_BC6U;
    default: return LAS_BC_NONE;
    }
}
static bool sample_cpu_upload(NvnTexture *tex, GlesTexture *host) {
    if (host->gpu_written) return true;  // preserve real GPU render-target content
    if (!tex->addr) return host->cpu_uploaded;
    if (tex->target != 1 || tex->layout.layers != 1 ||
        tex->layout.depth > 1 || !tex->layout.fmt) return false;
    const FormatInfo *fi=tex->layout.fmt;
    const LevelLayout l=tegra_level(&tex->layout,0);
    if (!fi->bpb || !l.wb || !l.hb || !l.w || !l.h || l.d != 1) return false;
    uint64_t size=tegra_total_size(&tex->layout);
    uint64_t raw=(uint64_t)l.wb*l.hb*fi->bpb;
    if (!size || l.offset >= size || raw > size - l.offset ||
        size > (64ull<<20) || !raw || raw > (32ull<<20) ||
        tex->addr < 0x7000000000ull || tex->addr >= 0x7320000000ull ||
        size > 0x7320000000ull-tex->addr) return false;
    const uint8_t *memory=(const uint8_t *)(uintptr_t)tex->addr;
    // Avoid hashing the same texture many times per frame. Static guest
    // images are rechecked periodically; linear atlases are rechecked each
    // frame to reflect updated glyphs.
    const uint64_t period = (tex->flags & 0x10) ? 1u : 60u;
    if (host->cpu_uploaded && g_frames >= host->last_cpu_check_frame &&
        g_frames - host->last_cpu_check_frame < period) {
        g_sample_cached++; return true;
    }
    host->last_cpu_check_frame = g_frames;
    uint64_t h=1469598103934665603ull;
    for (uint64_t i=0;i<size;i++) h=(h^memory[i])*1099511628211ull;
    if (host->cpu_uploaded && host->cpu_hash == h) {
        g_sample_cached++; return true;
    }
    uint8_t *linear=malloc((size_t)raw);
    if (!linear) return false;
    const uint8_t *src=memory+l.offset;
    const bool linear_storage=(tex->flags & 0x10)!=0;
    if (linear_storage) {
        uint64_t stride=tex->stride ? tex->stride : (uint64_t)l.wb*fi->bpb;
        if (stride < (uint64_t)l.wb*fi->bpb || stride > (64ull<<20) ||
            (uint64_t)(l.hb-1)*stride+(uint64_t)l.wb*fi->bpb > size-l.offset) {
            free(linear); return false;
        }
        for(uint32_t y=0;y<l.hb;y++)
            memcpy(linear+(uint64_t)y*l.wb*fi->bpb,
                   src+(uint64_t)y*stride,(uint64_t)l.wb*fi->bpb);
    } else {
        tegra_deswizzle(src,linear,l.wb,l.hb,1,fi->bpb,
                        l.block_height_log2,l.block_depth_log2);
    }
    FormatGL f=gpu_format(tex->format);
    if (!f.internal || f.attachment != GL_COLOR_ATTACHMENT0) {free(linear);return false;}
    uint8_t *pixels=linear;
    uint64_t bytes=raw;
    unsigned bc=bcn_type(tex->format);
    const bool astc=tex->format >= 0x79 && tex->format <= 0x94;
    if (bc || astc) {
        unsigned px=bc?las_bcn_pixel_bytes(bc):4;
        bytes=(uint64_t)l.w*l.h*px;
        if (!px || bytes > (64ull<<20)) {free(linear);return false;}
        pixels=malloc((size_t)bytes);
        if (!pixels) {free(linear);return false;}
        bool ok=bc ? las_bcn_decode(bc,linear,(size_t)raw,l.w,l.h,1,pixels,(size_t)bytes) : true;
        if (astc) astc_decode_ldr(linear,l.w,l.h,fi->bw,fi->bh,
                                  tex->format >= 0x87,pixels);
        free(linear);
        if (!ok) {free(pixels);return false;}
    }
    glBindTexture(GL_TEXTURE_2D,host->color);
    glPixelStorei(GL_UNPACK_ALIGNMENT,1);
    glTexSubImage2D(GL_TEXTURE_2D,0,0,0,(GLsizei)l.w,(GLsizei)l.h,
                    f.format,f.type,pixels);
    GLenum status=glGetError();
    glPixelStorei(GL_UNPACK_ALIGNMENT,4);
    if (pixels) free(pixels);
    if(status!=GL_NO_ERROR) {
        static unsigned warn;
        if(warn++<10) LOG("[gles] CPU texture upload error: format=%#x gl=%#x\n",tex->format,status);
        return false;
    }
    host->cpu_hash=h;
    host->cpu_uploaded=true;
    g_sample_uploaded_bytes+=bytes;
    return true;
}

static GLint sampler_wrap(uint32_t wrap) {
    switch(wrap) {
    case 0: case 7: return GL_CLAMP_TO_EDGE;
    case 1: return GL_REPEAT;
    case 6: return GL_MIRRORED_REPEAT;
    default: return 0; // border/mirror-clamp needs an exact extension path
    }
}
bool gles_sample_texture(NvnTexture *tex, NvnSamplerDesc *sampler,
                         int unit, bool shadow, uint8_t target) {
    if (!tex || unit < 0 || unit >= 32 || target != 1) {
        g_sample_fail++; return false;
    }
    GlesTexture *host=texture(tex);
    if (!host || !sample_cpu_upload(tex,host)) {g_sample_fail++;return false;}
    if (shadow && host->attachment != GL_DEPTH_ATTACHMENT &&
        host->attachment != GL_DEPTH_STENCIL_ATTACHMENT) {
        g_sample_fail++; return false;
    }
    GLint wrap_s=sampler?sampler_wrap(sampler->wrap[0]):GL_CLAMP_TO_EDGE;
    GLint wrap_t=sampler?sampler_wrap(sampler->wrap[1]):GL_CLAMP_TO_EDGE;
    if (!wrap_s || !wrap_t) {g_sample_fail++;return false;}
    GLuint sm=g_texture_samplers[unit];
    if (!sm) {g_sample_fail++;return false;}
    uint32_t mag=sampler?sampler->mag_filter:1, min=sampler?sampler->min_filter:1;
    glSamplerParameteri(sm,GL_TEXTURE_WRAP_S,wrap_s);
    glSamplerParameteri(sm,GL_TEXTURE_WRAP_T,wrap_t);
    glSamplerParameteri(sm,GL_TEXTURE_MIN_FILTER,
                        (min==1||min==3||min==5)?GL_LINEAR:GL_NEAREST);
    glSamplerParameteri(sm,GL_TEXTURE_MAG_FILTER,mag==1?GL_LINEAR:GL_NEAREST);
    glSamplerParameteri(sm,GL_TEXTURE_COMPARE_MODE,shadow?GL_COMPARE_REF_TO_TEXTURE:GL_NONE);
    if (shadow) glSamplerParameteri(sm,GL_TEXTURE_COMPARE_FUNC,GL_LEQUAL);
    glBindSampler((GLuint)unit,sm);
    glActiveTexture(GL_TEXTURE0+(GLenum)unit);
    glBindTexture(GL_TEXTURE_2D,host->color);
    g_sample_ok++;
    return true;
}
void gles_mark_texture_written(NvnTexture *tex) {
    if (!tex || !tex->backend) return;
    ((GlesTexture *)tex->backend)->gpu_written=true;
}

void gles_texture_destroyed(NvnTexture *tex) {
    if (!tex) return;
    // Finalization may run on the game thread while video decode submits
    // pixels. Remove any pending upload while holding the queue lock, before
    // the NVN object is freed by its owner.
    pthread_mutex_lock(&video_mutex);
    for (int i=0;i<GLES_VIDEO_QUEUE;i++) {
        if (video_queue[i].tex == tex) {
            free(video_queue[i].pixels);
            memset(&video_queue[i],0,sizeof video_queue[i]);
        }
    }
    pthread_mutex_unlock(&video_mutex);
    if (!tex->backend) return;
    GlesTexture *t = tex->backend;
    // NVN objects may be finalized by non-GL threads. Avoid invoking GLES
    // with no current context; a per-context deferred-delete queue is next.
    if (g_context && SDL_GL_GetCurrentContext() == g_context) {
        glDeleteFramebuffers(1, &t->framebuffer);
        glDeleteTextures(1, &t->color);
    }
    free(t);
    tex->backend = NULL;
}

// Video producers use independent guest/FFmpeg threads. This callback
// intentionally does NOT call GLES: pixels are copied into an owned queue
// and applied only by the thread holding the SDL GLES context.
void gles_upload_rgba(NvnTexture *t, const void *src, uint32_t w, uint32_t h, uint32_t stride) {
    uint64_t bytes=(uint64_t)w*h*4u;
    if (!t || !src || !w || !h || w>8192 || h>8192 ||
        stride<(uint64_t)w*4u || bytes>(64ull<<20)) {
        video_dropped++; return;
    }
    uint8_t *copy=malloc((size_t)bytes);
    if (!copy) {video_dropped++;return;}
    const uint8_t *in=src;
    for(uint32_t y=0;y<h;y++)
        memcpy(copy+(uint64_t)y*w*4u,in+(uint64_t)y*stride,(uint64_t)w*4u);
    pthread_mutex_lock(&video_mutex);
    int slot=-1;
    for(int i=0;i<GLES_VIDEO_QUEUE;i++)
        if(video_queue[i].tex==t) {slot=i;break;}
    if(slot<0)
        for(int i=0;i<GLES_VIDEO_QUEUE;i++)
            if(!video_queue[i].tex){slot=i;break;}
    if(slot<0) {slot=(int)(video_queued%GLES_VIDEO_QUEUE);video_dropped++;}
    free(video_queue[slot].pixels);
    video_queue[slot]=(PendingVideo){t,copy,w,h};
    video_queued++;
    pthread_mutex_unlock(&video_mutex);
}
static void gles_flush_video_queue(void) {
    // The queue lock remains held while uploading: texture finalization
    // cannot free the NVN object until the current upload finishes.
    pthread_mutex_lock(&video_mutex);
    for(int i=0;i<GLES_VIDEO_QUEUE;i++) {
        PendingVideo *q=&video_queue[i];
        if(!q->tex) continue;
        GlesTexture *tex=texture(q->tex);
        if(tex && tex->attachment==GL_COLOR_ATTACHMENT0 &&
           q->w<=tex->width && q->h<=tex->height &&
           (q->tex->format==0x25 || q->tex->format==0x19 ||
            q->tex->format==0x6d || q->tex->format==0x37 ||
            q->tex->format==0x38)) {
            glBindTexture(GL_TEXTURE_2D,tex->color);
            glPixelStorei(GL_UNPACK_ALIGNMENT,1);
            glTexSubImage2D(GL_TEXTURE_2D,0,0,0,q->w,q->h,
                            GL_RGBA,GL_UNSIGNED_BYTE,q->pixels);
            if(glGetError()==GL_NO_ERROR){
                tex->gpu_written=true;
                video_uploaded++;
            } else video_dropped++;
            glPixelStorei(GL_UNPACK_ALIGNMENT,4);
        } else video_dropped++;
        free(q->pixels);
        memset(q,0,sizeof *q);
    }
    pthread_mutex_unlock(&video_mutex);
}

static void clear_texture(NvnTexture *tex, const float *rgba, uint32_t mask,
                          const int32_t region[6]) {
    GlesTexture *t = texture(tex);
    if (!t || !t->framebuffer || t->attachment != GL_COLOR_ATTACHMENT0) return;
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    glViewport(0, 0, t->width, t->height);
    glEnable(GL_SCISSOR_TEST);
    if (region && region[3] > 0 && region[4] > 0)
        glScissor(region[0], region[1], region[3], region[4]);
    else
        glScissor(g_clear_scissor[0], g_clear_scissor[1],
                  g_clear_scissor[2], g_clear_scissor[3]);
    glColorMask(!!(mask & 1), !!(mask & 2), !!(mask & 4), !!(mask & 8));
    glClearColor(rgba[0], rgba[1], rgba[2], rgba[3]);
    glClear(GL_COLOR_BUFFER_BIT);
    gles_mark_texture_written(tex);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    g_clears++;
}


// NVN copy commands are essential for the render graph: scene passes often
// write offscreen targets, then copy/downsample into the displayed window
// texture. This is an actual GLES FBO blit, never a Vulkan/CPU placeholder.
typedef struct {
    uint64_t tex;
    NvnTextureView view;
    uint8_t has_view;
    int32_t region[6];
} GlesTexRef;
static bool copy_view_base_only(const GlesTexRef *r, const NvnTexture *tex) {
    if (!r->has_view) return true;
    if ((r->view.setmask & 1) && r->view.base_level != 0) return false;
    if ((r->view.setmask & 2) && r->view.min_layer != 0) return false;
    if ((r->view.setmask & 4) && r->view.format &&
        r->view.format != tex->format) return false;
    // Color channel swizzles are a shader-view property, not a texel-copy
    // conversion; Vulkan's raw copy path likewise ignores swizzle.
    return true;
}
static bool gles_copy_texture(const GlesTexRef *from, const GlesTexRef *to,
                              bool downsample, uint64_t flags) {
    g_copies_attempted++;
    NvnTexture *src=(NvnTexture *)(uintptr_t)from->tex;
    NvnTexture *dst=(NvnTexture *)(uintptr_t)to->tex;
    if (!src || !dst || src == dst || !copy_view_base_only(from,src) ||
        !copy_view_base_only(to,dst) || src->target != 1 || dst->target != 1 ||
        src->samples > 1 || dst->samples > 1) goto rejected;
    GlesTexture *s=texture(src), *d=texture(dst);
    if (!s || !d || !s->framebuffer || !d->framebuffer) goto rejected;
    // If the source contains CPU texels rather than a rendered image,
    // populate its native texture before starting the GPU->GPU copy.
    if (!s->gpu_written && src->addr && !sample_cpu_upload(src,s)) goto rejected;
    if (!s->gpu_written && !s->cpu_uploaded) goto rejected;
    const bool src_depth=s->attachment!=GL_COLOR_ATTACHMENT0;
    const bool dst_depth=d->attachment!=GL_COLOR_ATTACHMENT0;
    if (src_depth!=dst_depth) goto rejected;
    if (src_depth && src->format!=dst->format) goto rejected;
    if (src_depth && from->region[3] && to->region[3] &&
        (from->region[3]!=to->region[3] || from->region[4]!=to->region[4]))
        goto rejected;
    int sx=from->region[0], sy=from->region[1],
        dx=to->region[0], dy=to->region[1];
    int sw=from->region[3]?from->region[3]:s->width-sx;
    int sh=from->region[4]?from->region[4]:s->height-sy;
    int dw=to->region[3]?to->region[3]:d->width-dx;
    int dh=to->region[4]?to->region[4]:d->height-dy;
    if (sx<0 || sy<0 || dx<0 || dy<0 || sw<=0 || sh<=0 ||
        dw<=0 || dh<=0 || (uint64_t)sx+sw>(unsigned)s->width ||
        (uint64_t)sy+sh>(unsigned)s->height ||
        (uint64_t)dx+dw>(unsigned)d->width ||
        (uint64_t)dy+dh>(unsigned)d->height) goto rejected;
    const GLbitfield mask=src_depth ? GL_DEPTH_BUFFER_BIT : GL_COLOR_BUFFER_BIT;
    const GLenum filter=src_depth ? GL_NEAREST :
        (downsample || (flags&1)) ? GL_LINEAR : GL_NEAREST;
    // Only successful exact-size color blits or GLES-defined scaling:
    // depth blits require equal dimensions.
    if (src_depth && (sw!=dw || sh!=dh)) goto rejected;
    // Clear inherited errors so the result is meaningful for this command.
    for (int i=0; i<8 && glGetError()!=GL_NO_ERROR; ++i) {}
    glBindFramebuffer(GL_READ_FRAMEBUFFER,s->framebuffer);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER,d->framebuffer);
    if (!src_depth) {
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        const GLenum buf=GL_COLOR_ATTACHMENT0;
        glDrawBuffers(1,&buf);
    }
    glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);
    glDepthMask(GL_TRUE);
    glBlitFramebuffer(sx,sy,sx+sw,sy+sh,dx,dy,dx+dw,dy+dh,mask,filter);
    GLenum error=glGetError();
    if (error != GL_NO_ERROR) {
        if (g_copies_failed < 12)
            LOG("[gles-copy] GL error=%#x src=%#x %dx%d dst=%#x %dx%d\n",
                error, src->format, sw, sh, dst->format, dw, dh);
        goto rejected;
    }
    d->gpu_written=true;
    g_copies_succeeded++;
    if (g_copies_succeeded<=8)
        LOG("[gles-copy] completed GPU blit src=%llu fmt=%#x %dx%d -> dst=%llu fmt=%#x %dx%d\n",
            (unsigned long long)src->debug_id,src->format,sw,sh,
            (unsigned long long)dst->debug_id,dst->format,dw,dh);
    return true;
rejected:
    g_copies_failed++;
    return false;
}

static void execute_list(uint64_t handle, int depth) {
    if (!handle || depth > 8) return;
    uint64_t addr = handle;
    for (int guard = 0; guard < 1000000; ++guard) {
        CmdRec *r = (CmdRec *)(uintptr_t)addr;
        if (!r->size || r->size > (1u << 20)) {
            LOG("[gles] invalid NVN record (opcode=%u size=%u)\n", r->op, r->size);
            break;
        }
        switch (r->op) {
        case CMD_END: return;
        case CMD_JUMP:
            if (r->x[0] == addr) return;
            addr = r->x[0];
            continue;
        case CMD_CALL: {
            uint64_t *handles = (uint64_t *)r->extra;
            if (r->x[0] <= 4096) for (uint64_t i = 0; i < r->x[0]; ++i)
                execute_list(handles[i], depth + 1);
            break;
        }
        case CMD_SET_RENDER_TARGETS: {
            struct {
                uint64_t tex[8];
                NvnTextureView views[8];
                uint8_t has_view[8];
                uint64_t depth;
                NvnTextureView dview;
                uint8_t has_dview;
            } *rt = (void *)r->extra;
            for (int i = 0; i < 8; ++i)
                g_color[i] = i < (int)r->x[0] ? (NvnTexture *)(uintptr_t)rt->tex[i] : NULL;
            g_depth = (NvnTexture *)(uintptr_t)rt->depth;
            gles_draw_state(r);
            break;
        }
        case CMD_SET_SCISSORS:
            if (r->x[0] == 0 && r->x[1] && r->size >= sizeof(CmdRec) + 16)
                memcpy(g_clear_scissor, r->extra, 16);
            gles_draw_state(r);
            break;
        case CMD_CLEAR_COLOR: {
            int index = (int)r->x[0];
            if (index >= 0 && index < 8 && g_color[index] && r->x[5] == 0)
                clear_texture(g_color[index], (const float *)r->extra, (uint32_t)r->x[2], NULL);
            else g_unsupported++;
            break;
        }
        case CMD_CLEAR_DEPTH_STENCIL:
            if (g_depth && gles_clear_depth(g_depth, r->x[0] != 0, r->f[0],
                                            r->x[2] != 0, (uint32_t)r->x[1],
                                            (uint32_t)r->x[2])) g_clears++;
            else g_unsupported++;
            break;
        case CMD_CLEAR_TEXTURE: {
            struct {
                uint64_t tex;
                NvnTextureView view;
                uint8_t has_view;
                int32_t region[6];
                float color[4];
            } *ct = (void *)r->extra;
            if (ct->tex && !r->x[6])
                clear_texture((NvnTexture *)(uintptr_t)ct->tex, ct->color,
                              r->x[4] ? (uint32_t)r->x[4] : 15, ct->region);
            else g_unsupported++;
            break;
        }
        case CMD_COPY_TEXTURE_TO_TEXTURE:
        case CMD_DOWNSAMPLE: {
            if (r->size >= sizeof(CmdRec)+2*sizeof(GlesTexRef)) {
                const GlesTexRef *refs=(const GlesTexRef *)(const void *)r->extra;
                gles_copy_texture(&refs[0],&refs[1],r->op==CMD_DOWNSAMPLE,r->x[6]);
            } else g_copies_failed++;
            break;
        }
        case CMD_COPY_BUFFER_TO_BUFFER:
            memmove((void *)(uintptr_t)r->x[1], (const void *)(uintptr_t)r->x[0], (size_t)r->x[2]);
            break;
        case CMD_REPORT_COUNTER: {
            uint64_t *out = (uint64_t *)(uintptr_t)r->x[1];
            if (out) { out[0] = 0; out[1] = (uint64_t)((unsigned __int128)plat_now_ns() * 384 / 625); }
            break;
        }
        case CMD_DRAW_ARRAYS:
            if (!gles_draw_execute(r, false)) g_draws_unsupported++;
            break;
        case CMD_DRAW_ELEMENTS:
            if (!gles_draw_execute(r, true)) g_draws_unsupported++;
            break;
        case CMD_DRAW_ARRAYS_INDIRECT: case CMD_DRAW_ELEMENTS_INDIRECT:
        case CMD_DRAW_TEXTURE:
            g_draws_unsupported++;
            break;
        case CMD_DISPATCH: case CMD_DISPATCH_INDIRECT:
            g_dispatch_unsupported++;
            break;
        // Other state binds are recorded for future porting; they must NOT
        // accidentally be interpreted as Vulkan draw calls in GLES mode.
        default:
            if (!gles_draw_state(r)) {
                g_unsupported++;
                g_last_unsupported = (int)r->op;
            }
            break;
        }
        addr += r->size;
    }
}

void gles_execute(uint64_t handle) {
    if (!g_context) return;
    if (g_draw_needs_reset) {
        gles_draw_reset();
        g_draw_needs_reset = false;
    }
    gles_flush_video_queue();
    execute_list(handle, 0);
    ++g_executed_lists;
    // Keep a short-lived startup snapshot even when Android kills the
    // activity before the first 120 presented frames. The first two writes
    // are useful for boot failures; later writes are logarithmically spaced.
    if ((g_executed_lists == 1 || g_executed_lists == 16 ||
         g_executed_lists == 128 || g_executed_lists == 1024) &&
        g_last_checkpoint != g_executed_lists) {
        g_last_checkpoint = g_executed_lists;
        LOG("[gles] startup NVN lists=%" PRIu64 " %s\n",
            g_executed_lists, gles_stats());
        report();
    }
}

void gles_present(NvnTexture *tex) {
    if (!g_context) return;
    gles_flush_video_queue();
    // Presentation textures can be written by NVN copies or supplied by
    // the guest window directly. Resolve them through the native GLES cache.
    GlesTexture *t = tex ? texture(tex) : NULL;
    g_last_present_gl_error=GL_NO_ERROR;
    g_last_present_id = tex ? (uint32_t)tex->debug_id : 0;
    g_last_present_format = tex ? tex->format : 0;
    if (!t) g_present_missing++;
    else if (t->gpu_written || t->cpu_uploaded) g_present_written++;
    else g_present_unwritten++;
    int w = 1, h = 1;
    SDL_GetWindowSizeInPixels(g_window, &w, &h);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, w, h);
    // NVN draw state must not leak into final presentation. Otherwise a
    // full-screen triangle may be culled, scissored or color-masked out.
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_STENCIL_TEST);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_CULL_FACE);
    glDisable(GL_BLEND);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthMask(GL_FALSE);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    if (t) {
        // A game sampler can still occupy unit 0. Do not reuse its wrap,
        // compare or mipmap state for the presentation texture.
        glBindSampler(0, 0);
        glUseProgram(g_present_program);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, t->color);
        glUniform1i(g_present_sampler, 0);
        glBindVertexArray(g_vertex_array);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        g_last_present_gl_error = glGetError();
        if (g_last_present_gl_error != GL_NO_ERROR) {
            g_present_gl_errors++;
            if (g_present_gl_errors <= 10)
                LOG("[gles-present] GLES draw error=%#x tex=%llu fmt=%#x\n",
                    g_last_present_gl_error,
                    (unsigned long long)tex->debug_id, tex->format);
        }
    }
    if (!SDL_GL_SwapWindow(g_window) && g_present_gl_errors++ < 10)
        LOG("[gles-present] swap failed: %s\n", SDL_GetError());
    g_frames++;
    if (g_frames == 1 || g_frames == 16 || g_frames == 64 ||
        g_frames % 120 == 0) {
        LOG("[gles-present] frame=%" PRIu64 " tex=%llu fmt=%#x object=%u"
            " gpu_written=%d cpu_uploaded=%d present_err=%#x copy_ok=%" PRIu64
            "/%" PRIu64 "\n", g_frames,
            (unsigned long long)(tex ? tex->debug_id : 0),
            tex ? tex->format : 0, t ? t->color : 0,
            t ? t->gpu_written : 0, t ? t->cpu_uploaded : 0,
            g_last_present_gl_error, g_copies_succeeded, g_copies_attempted);
    }
    if (g_frames == 1 || g_frames == 16 || g_frames == 64 ||
        g_frames % 120 == 0) {
        LOG("[gles] %s\n", gles_stats());
        report();
    }
    extern void input_frame(uint64_t frame);
    input_frame(g_frames);
}

void gles_finish(void) {
    if (g_context && SDL_GL_GetCurrentContext() == g_context) glFinish();
}
void gles_clear_window(void) {
    if (!g_context || SDL_GL_GetCurrentContext() != g_context) return;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    SDL_GL_SwapWindow(g_window);
}
void gles_reset(void) {
    memset(g_color, 0, sizeof g_color);
    g_depth = NULL;
    g_clear_scissor[0] = g_clear_scissor[1] = 0;
    g_clear_scissor[2] = g_clear_scissor[3] = 16384;
    // Only a thread with the current GL context can delete shader objects.
    // The next NVN executor call resets them after an in-place game reboot.
    g_draw_needs_reset = true;
    gles_finish();
    report();
}
