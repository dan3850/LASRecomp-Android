// LASRecomp OpenGL ES backend, independent of Vulkan. Initial NVN subset:
// render targets, colour clears, buffer copies, timestamp reports, presentation.
// Graphics/compute draws are intentionally counted as UNSUPPORTED until the
// Maxwell->GLSL ES translator, buffers and samplers are implemented.
#include "gles.h"
#include "draw.h"
#include <GLES3/gl3.h>
#include <inttypes.h>
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
static char g_stats[512];
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
             " skipped_draws=%" PRIu64 " skipped_compute=%" PRIu64 " [%s]",
             g_frames, g_clears, gles_draw_native_count(), gles_draw_program_count(),
             gles_draw_shader_failure_count(), g_draws_unsupported, g_dispatch_unsupported,
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
    case 0x0D: return (FormatGL){GL_RG8, GL_RG, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x19: case 0x25: case 0x6D:
        return (FormatGL){GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
    case 0x29: case 0x71:
        return (FormatGL){GL_RGBA16F, GL_RGBA, GL_HALF_FLOAT, GL_COLOR_ATTACHMENT0};
    case 0x2E: case 0x76:
        return (FormatGL){GL_RGBA32F, GL_RGBA, GL_FLOAT, GL_COLOR_ATTACHMENT0};
    case 0x37: case 0x38:
        return (FormatGL){GL_SRGB8_ALPHA8, GL_RGBA, GL_UNSIGNED_BYTE, GL_COLOR_ATTACHMENT0};
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
        static int warned;
        if (warned++ < 15)
            LOG("[gles] native framebuffer unsupported: fmt=%#x size=%ux%u status=%#x\n",
                tex->format, tex->width, tex->height, status);
        glDeleteFramebuffers(1, &t->framebuffer);
        glDeleteTextures(1, &t->color);
        free(t);
        return NULL;
    }
    tex->backend = t;
    return t;
}

bool gles_draw_framebuffer(NvnTexture *color, NvnTexture *depth, int *w, int *h) {
    GlesTexture *t = texture(color);
    if (!color && depth) {
        // Depth-only pre-passes do not have a color attachment.
        GlesTexture *z = texture(depth);
        if (!z || z->attachment == GL_COLOR_ATTACHMENT0) return false;
        glBindFramebuffer(GL_FRAMEBUFFER, z->framebuffer);
        if (w) *w = z->width;
        if (h) *h = z->height;
        return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    }
    if (!t || t->attachment != GL_COLOR_ATTACHMENT0) return false;
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    if (depth) {
        GlesTexture *z = texture(depth);
        if (!z || z->attachment == GL_COLOR_ATTACHMENT0 ||
            z->width != t->width || z->height != t->height) return false;
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
    if (!z || z->attachment == GL_COLOR_ATTACHMENT0) return false;
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
    if (bits) glClear(bits);
    glStencilMask(0xFF);
    glDepthMask(GL_TRUE);
    return bits != 0;
}

void gles_texture_destroyed(NvnTexture *tex) {
    if (!tex || !tex->backend) return;
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

// Video decode callbacks can run on non-GL threads; a safe upload queue
// must be implemented before touching a GLES texture here.
void gles_upload_rgba(NvnTexture *t, const void *src, uint32_t w, uint32_t h, uint32_t stride) {
    (void)t; (void)src; (void)w; (void)h; (void)stride;
    g_unsupported++;
}

static void clear_texture(NvnTexture *tex, const float *rgba, uint32_t mask,
                          const int32_t region[6]) {
    GlesTexture *t = texture(tex);
    if (!t || t->attachment != GL_COLOR_ATTACHMENT0) return;
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
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    g_clears++;
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
    GlesTexture *t = tex ? tex->backend : NULL;
    if (t) {
        glUseProgram(g_present_program);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, t->color);
        glUniform1i(g_present_sampler, 0);
        glBindVertexArray(g_vertex_array);
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }
    SDL_GL_SwapWindow(g_window);
    g_frames++;
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
