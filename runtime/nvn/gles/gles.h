// Independent GLES NVN backend. Never calls Vulkan or PixelCopy.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <SDL3/SDL.h>
#include "../nvn.h"

#ifdef __ANDROID__
bool gles_selected(void);
void gles_init(SDL_Window *window);
void gles_reset(void);
void gles_execute(uint64_t handle);
void gles_present(NvnTexture *tex);
void gles_clear_window(void);
void gles_texture_destroyed(NvnTexture *tex);
void gles_upload_rgba(NvnTexture *tex, const void *data, uint32_t width, uint32_t height, uint32_t stride);
void gles_finish(void);
uint64_t gles_frame_count(void);
const char *gles_stats(void);

#else
// Other platforms keep their original Metal/Vulkan backend and link unchanged.
static inline bool gles_selected(void) { return false; }
static inline void gles_init(SDL_Window *window) { (void)window; }
static inline void gles_reset(void) {}
static inline void gles_execute(uint64_t handle) { (void)handle; }
static inline void gles_present(NvnTexture *tex) { (void)tex; }
static inline void gles_clear_window(void) {}
static inline void gles_texture_destroyed(NvnTexture *tex) { (void)tex; }
static inline void gles_upload_rgba(NvnTexture *tex, const void *data, uint32_t width,
                                    uint32_t height, uint32_t stride) {
    (void)tex; (void)data; (void)width; (void)height; (void)stride;
}
static inline void gles_finish(void) {}
static inline uint64_t gles_frame_count(void) { return 0; }
static inline const char *gles_stats(void) { return ""; }
#endif
