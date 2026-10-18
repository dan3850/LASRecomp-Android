// Native GLES Maxwell draw path. No Vulkan resources, SPIR-V or PixelCopy.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "../nvn.h"
void gles_draw_init(void);
void gles_draw_reset(void);
bool gles_draw_state(const CmdRec *cmd);
bool gles_draw_execute(const CmdRec *cmd, bool indexed);
uint64_t gles_draw_native_count(void);
uint64_t gles_draw_program_count(void);
uint64_t gles_draw_shader_failure_count(void);
const char *gles_draw_rejection_stats(void);
