// Persistent, bounded pipeline recipes. No guest addresses or Vulkan handles on disk.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { REPLAY_GRAPHICS = 1, REPLAY_COMPUTE = 2, REPLAY_STATE_MAX = 1024 };
typedef struct {
    uint32_t vendor, device, driver, api, features, state_abi;
    uint8_t uuid[16];
    char code[128];
} ReplayIdentity;
typedef struct {
    uint32_t kind, state_size;
    const void *state;
    const uint32_t *code[2];
    uint32_t words[2];
} ReplayRecipe;
typedef void *(*ReplayBuild)(const ReplayRecipe *, void *demand_context);
typedef void (*ReplayDestroy)(void *object);

// Start once after device/shader initialization. Only disk IO and preparation
// run on background threads; demand waits only for its exact recipe.
void replay_start(const ReplayIdentity *, ReplayBuild, ReplayDestroy, void (*checkpoint)(void));
void *replay_get(const ReplayRecipe *, void *demand_context);
void replay_stats(char *text, size_t capacity);
void replay_wait_startup(void); // tests / explicit preparation barrier, not the render loop
void replay_stop(void);         // join background work and persist successful recipes
void replay_destroy(void);      // after stop + GPU idle + all demand callers stopped
