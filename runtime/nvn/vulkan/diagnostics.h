#pragma once
#include <stdbool.h>
#include <stdio.h>
enum {
    VD_TEXTURE, VD_BCN_DECODE, VD_UNSUPPORTED_FORMAT, VD_UPLOAD_SKIPPED,
    VD_GLYPH_UPLOAD, VD_ZERO_GMEM, VD_SHADER_ERROR, VD_PIPELINE_ERROR,
    VD_MISSING_TEXTURE, VD_CAPTURE, VD_INFO, VD_DRAW, VD_COUNT
};
void vk_diag_event(unsigned kind, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void vk_diag_info(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
bool vk_diag_begin_capture(void);
void vk_diag_finish_capture(bool frame_saved);
void vk_diag_texture_report(FILE *out);
void vk_diag_capture_atlases(void);
bool vk_diag_trace_draw(void);
