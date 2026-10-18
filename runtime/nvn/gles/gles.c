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
} GlesTexture;

static SDL_Window *g_window;
static SDL_GLContext g_context;
static GLuint g_present_program, g_vertex_array;
static GLint g_present_sampler;
static NvnTexture *g_color[8];
static bool g_draw_needs_reset;
static uint64_t g_frames, g_clears, g_draws_unsupported, g_dispatch_unsupported, g_unsupported;
static int g_last_unsupported = -1;
static char g_stats[256];

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
             " skipped_draws=%" PRIu64 " skipped_compute=%" PRIu64,
             g_frames, g_clears, gles_draw_native_count(), gles_draw_program_count(),
             gles_draw_shader_failure_count(), g_draws_unsupported, g_dispatch_unsupported);
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

static GlesTexture *texture(NvnTexture *tex) {
    if (!tex || !tex->width || !tex->height || tex->width > 8192 || tex->height > 8192)
        return NULL;
    if (tex->backend) return tex->backend;
    GlesTexture *t = calloc(1, sizeof *t);
    if (!t) return NULL;
    t->width = (GLsizei)tex->width;
    t->height = (GLsizei)tex->height;
    glGenTextures(1, &t->color);
    glBindTexture(GL_TEXTURE_2D, t->color);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, t->width, t->height,
                 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glGenFramebuffers(1, &t->framebuffer);
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->color, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        LOG("[gles] framebuffer incomplete for texture %#x %ux%u\n", tex->format, tex->width, tex->height);
        glDeleteFramebuffers(1, &t->framebuffer);
        glDeleteTextures(1, &t->color);
        free(t);
        return NULL;
    }
    tex->backend = t;
    return t;
}

bool gles_draw_framebuffer(NvnTexture *tex, int *w, int *h) {
    GlesTexture *t = texture(tex);
    if (!t) return false;
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    if (w) *w = t->width;
    if (h) *h = t->height;
    return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
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

static void clear_texture(NvnTexture *tex, const float *rgba, uint32_t mask) {
    GlesTexture *t = texture(tex);
    if (!t) return;
    glBindFramebuffer(GL_FRAMEBUFFER, t->framebuffer);
    glViewport(0, 0, t->width, t->height);
    glDisable(GL_SCISSOR_TEST);
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
            gles_draw_state(r);
            break;
        }
        case CMD_CLEAR_COLOR: {
            int index = (int)r->x[0];
            if (index >= 0 && index < 8 && g_color[index] && r->x[5] == 0)
                clear_texture(g_color[index], (const float *)r->extra, (uint32_t)r->x[2]);
            else g_unsupported++;
            break;
        }
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
                              r->x[4] ? (uint32_t)r->x[4] : 15);
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
}

void gles_present(NvnTexture *tex) {
    if (!g_context) return;
    int w = 1, h = 1;
    SDL_GetWindowSizeInPixels(g_window, &w, &h);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, w, h);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_BLEND);
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
    if (g_frames % 120 == 0) {
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
    // Only a thread with the current GL context can delete shader objects.
    // The next NVN executor call resets them after an in-place game reboot.
    g_draw_needs_reset = true;
    gles_finish();
    report();
}
