#pragma once
#include <stdint.h>

// main/sdk are loaded and dispatch_init() has run before this call.
void mario_startup(uint64_t stack_size, int priority);
