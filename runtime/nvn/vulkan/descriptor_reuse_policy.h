// Canonical descriptor-set content for exact in-submission reuse.
// Vulkan handles are encoded as uint64; no unstable host pointers are stored.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define LAS_DS_LIMIT 24u
#define LAS_DS_SLOTS 4096u
typedef struct { uint32_t binding, type; uint64_t a,b,c; } LasDsBind;
typedef struct {
 uint64_t layout;
 uint32_t count, reserved;
 LasDsBind binds[LAS_DS_LIMIT];
} LasDsKey;
static inline uint64_t las_ds_hash(const LasDsKey *key) {
 if (!key || key->count > LAS_DS_LIMIT) return 0;
 const uint8_t *p=(const uint8_t*)key;
 size_t size=offsetof(LasDsKey,binds)+key->count*sizeof key->binds[0];
 uint64_t h=UINT64_C(14695981039346656037);
 for (size_t i=0;i<size;++i) { h^=p[i]; h*=UINT64_C(1099511628211); }
 return h ? h : 1;
}
static inline bool las_ds_equal(const LasDsKey *a,const LasDsKey *b) {
 if (!a || !b || a->count>LAS_DS_LIMIT || b->count>LAS_DS_LIMIT ||
     a->count!=b->count) return false;
 return !memcmp(a,b,offsetof(LasDsKey,binds)+a->count*sizeof a->binds[0]);
}
static inline bool las_ds_valid(uint64_t seq,uint64_t needed,
 uint64_t hash,uint64_t expected,const LasDsKey *previous,const LasDsKey *current) {
 return seq==needed && hash==expected && las_ds_equal(previous,current);
}
