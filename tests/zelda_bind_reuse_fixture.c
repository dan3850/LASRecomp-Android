/* Actual descriptor cache and delayed recorder; Vulkan endpoints are a model. */
#include "nx/gpu/shader/shader.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef u64 VkDescriptorSet, VkDescriptorSetLayout, VkDescriptorPool, VkBuffer, VkBufferView;
typedef u64 VkImageView, VkSampler, VkCommandBuffer;
typedef u32 VkDescriptorType, VkImageLayout;
typedef struct { VkBuffer buffer; u64 offset, range; } VkDescriptorBufferInfo;
typedef struct { VkSampler sampler; VkImageView imageView; VkImageLayout imageLayout; } VkDescriptorImageInfo;
typedef struct {
    u32 sType; const void* pNext; VkDescriptorSet dstSet;
    u32 dstBinding, dstArrayElement, descriptorCount; VkDescriptorType descriptorType;
    const VkDescriptorImageInfo* pImageInfo; const VkDescriptorBufferInfo* pBufferInfo;
    const VkBufferView* pTexelBufferView;
} VkWriteDescriptorSet;
#define VK_NULL_HANDLE 0
#define VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET 35
#define VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER 6
#define VK_DESCRIPTOR_TYPE_STORAGE_BUFFER 7
#define VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC 8
#define VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC 9
#define VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER 4
#define VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER 5
#define VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER 1
#define VK_DESCRIPTOR_TYPE_STORAGE_IMAGE 3
#define VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE 2
#define LOG(...) printf(__VA_ARGS__)
#define LOG_LIMIT(n, ...) ((void)0)
#define REC_AL(n) (((u64)(n) + 15) & ~15ull)
#include "desc_types_actual.inc"
#include "record_types_actual.inc"
static struct { u64 dev; } g_vk = {1};
static u64 frame = 1;
static int g_rec = 1, fail_alloc, advance_on_create;
static u64 mix_calls, allocations, updates, bindings, resets;
static u64 g_vk_dset_new, g_vk_dset_reused;
static u64 vk_frame_id(void) { return frame; }
static u32 vk_frame_slot(void) { return (u32)(frame % VK_FRAMES); }
static VkCommandBuffer vk_cmd(void) { if (advance_on_create) { advance_on_create = 0; frame++; } return 1; }
typedef void (*RecFn)(const void*);
typedef struct { RecFn fn; void* data; } Event;
static Event events[8192];
static u32 nevents;
static void* rec_push(RecFn fn, u64 bytes) {
    assert(nevents < sizeof events / sizeof *events);
    void* p = calloc(1, bytes); assert(p); events[nevents++] = (Event){fn, p}; return p;
}
static void rec_commit(void) { }
static void drain(void) {
    for (u32 i = 0; i < nevents; i++) { events[i].fn(events[i].data); free(events[i].data); }
    nevents = 0;
}
static void vk_rec_sync(void) { drain(); }
#include "write_size_actual.inc"
#include "write_info_actual.inc"
typedef struct { VkWriteDescriptorSet* w; u32 n; } Contents;
typedef struct { Contents c; u32 slot; int valid; } SetModel;
static SetModel sets[4096];
static u32 next_set;
static void contents_free(Contents* c) {
    for (u32 i = 0; i < c->n; i++) free((void*)write_info(&c->w[i]));
    free(c->w); memset(c, 0, sizeof *c);
}
static Contents contents_copy(u32 n, const VkWriteDescriptorSet* writes) {
    Contents c = {.n = n, .w = calloc(n ? n : 1, sizeof *writes)}; assert(c.w);
    for (u32 i = 0; i < n; i++) {
        c.w[i] = writes[i]; size_t bytes = (size_t)write_info_size(&writes[i]);
        void* data = malloc(bytes ? bytes : 1); assert(data); memcpy(data, write_info(&writes[i]), bytes);
        c.w[i].pBufferInfo = NULL; c.w[i].pImageInfo = NULL; c.w[i].pTexelBufferView = NULL;
        switch (writes[i].descriptorType) {
        case 6: case 7: case 8: case 9: c.w[i].pBufferInfo = data; break;
        case 4: case 5: c.w[i].pTexelBufferView = data; break;
        default: c.w[i].pImageInfo = data; break;
        }
    }
    return c;
}
static int contents_equal(const Contents* a, const Contents* b) {
    if (a->n != b->n) return 0;
    for (u32 i = 0; i < a->n; i++) {
        const VkWriteDescriptorSet *x = a->w + i, *y = b->w + i;
        if (x->dstBinding != y->dstBinding || x->dstArrayElement != y->dstArrayElement ||
            x->descriptorCount != y->descriptorCount || x->descriptorType != y->descriptorType) return 0;
        for (u32 j = 0; j < x->descriptorCount; j++) {
            switch (x->descriptorType) {
            case 6: case 7: case 8: case 9:
                if (x->pBufferInfo[j].buffer != y->pBufferInfo[j].buffer || x->pBufferInfo[j].offset != y->pBufferInfo[j].offset ||
                    x->pBufferInfo[j].range != y->pBufferInfo[j].range) return 0;
                break;
            case 4: case 5: if (x->pTexelBufferView[j] != y->pTexelBufferView[j]) return 0; break;
            default:
                if (x->pImageInfo[j].sampler != y->pImageInfo[j].sampler || x->pImageInfo[j].imageView != y->pImageInfo[j].imageView ||
                    x->pImageInfo[j].imageLayout != y->pImageInfo[j].imageLayout) return 0;
            }
        }
    }
    return 1;
}
static VkDescriptorSet rec_alloc(RecPools* pools, VkDescriptorSetLayout layout) {
    (void)layout; allocations++;
    if (fail_alloc) return 0;
    assert(next_set + 1 < sizeof sets / sizeof *sets); u32 id = ++next_set;
    sets[id].slot = (u32)(pools - g_rpools); sets[id].valid = 1; return id;
}
static VkDescriptorSet vk_desc_alloc(VkDescriptorSetLayout layout) { return rec_alloc(&g_rpools[vk_frame_slot()], layout); }
static void vkUpdateDescriptorSets(u64 dev, u32 n, const VkWriteDescriptorSet* w, u32 copies, const void* copy) {
    assert(dev == 1 && !copies && !copy); updates++;
    if (!n) return;
    VkDescriptorSet set = w[0].dstSet; assert(set && set <= next_set && sets[set].valid);
    contents_free(&sets[set].c); sets[set].c = contents_copy(n, w);
}
static void vkResetDescriptorPool(u64 dev, VkDescriptorPool pool, u32 flags) {
    assert(dev == 1 && !flags && pool && pool <= VK_FRAMES); resets++;
    for (u32 i = 1; i <= next_set; i++) if (sets[i].slot + 1 == pool) sets[i].valid = 0;
}
#include "standin_actual.inc"
#include "real_actual.inc"
#include "new_run_actual.inc"
#include "new_set_actual.inc"
#include "frame_reset_actual.inc"
#include "reset_actual.inc"
#include "mix_actual.inc"
static u64 counted_mix(u64 h, u64 v, u64 m) { mix_calls++; return dset_mix(h, v, m); }
#define dset_mix counted_mix
#include "baseline_actual.inc"
#include "original_changed.inc"
#undef dset_mix
#include "bind_reuse.h"
typedef struct { VkDescriptorSet set; Contents expected; } Bind;
static void bind_run(const void* p) {
    const Bind* b = p; VkDescriptorSet set = rec_set_real(b->set);
    assert(set && set <= next_set && sets[set].valid && contents_equal(&sets[set].c, &b->expected));
    bindings++; Contents c = b->expected; contents_free(&c);
}
static void request(int optimized, VkDescriptorSetLayout layout, DescWrites* d) {
    VkDescriptorSet set = optimized ? desc_set_cached(layout, d) : baseline_cached(layout, d);
    assert(set); Bind* b = rec_push(bind_run, sizeof *b); *b = (Bind){set, contents_copy(d->n, d->w)};
}
static void fill(DescWrites* d, int array) {
    memset(d, 0xa5, sizeof *d); d->n = array ? 2 : 3;
    d->bi[0] = (VkDescriptorBufferInfo){101, 256, 4096};
    d->w[0] = (VkWriteDescriptorSet){.sType = 35, .dstBinding = 0, .descriptorCount = 1, .descriptorType = 6, .pBufferInfo = &d->bi[0]};
    for (u32 j = 0; j < SNX_TEX_ARRAY; j++) {
        d->table[j] = (VkDescriptorImageInfo){7, 500 + j, 5};
        d->depth_table[j] = (VkDescriptorImageInfo){8, 900 + j, 5};
    }
    if (array) {
        d->w[0] = (VkWriteDescriptorSet){.sType = 35, .dstBinding = SNX_VKB_TEXARRAY, .descriptorCount = SNX_TEX_ARRAY,
                                       .descriptorType = 1, .pImageInfo = d->table};
        d->w[1] = (VkWriteDescriptorSet){.sType = 35, .dstBinding = SNX_VKB_TEXDEPTH, .descriptorCount = SNX_TEX_ARRAY,
                                       .descriptorType = 1, .pImageInfo = d->depth_table};
    } else {
        d->ii[1] = (VkDescriptorImageInfo){9, 201, 5}; d->ii[2] = (VkDescriptorImageInfo){0, 202, 1};
        d->w[1] = (VkWriteDescriptorSet){.sType = 35, .dstBinding = 34, .descriptorCount = 1, .descriptorType = 1, .pImageInfo = &d->ii[1]};
        d->w[2] = (VkWriteDescriptorSet){.sType = 35, .dstBinding = 98, .descriptorCount = 1, .descriptorType = 3, .pImageInfo = &d->ii[2]};
    }
}
static void reset_world(void) {
    drain();
    for (u32 i = 1; i <= next_set; i++) contents_free(&sets[i].c);
    memset(sets, 0, sizeof sets); memset(g_rset, 0, sizeof g_rset); memset(g_rpools, 0, sizeof g_rpools);
    memset(snx_br_states, 0, sizeof snx_br_states); snx_br_replace = 0;
    for (u32 i = 0; i < VK_FRAMES; i++) { g_rpools[i].pool[0] = i + 1; g_rpools[i].npool = 1; }
    g_rset_next = REC_SETS - 2; next_set = 0; frame += 100;
    mix_calls = allocations = updates = bindings = resets = g_vk_dset_new = g_vk_dset_reused = 0;
    fail_alloc = advance_on_create = 0;
}
typedef struct { u64 mixes, allocations, bindings, saved_mixes, hits, key_bytes; } Work;
static Work run(int optimized, int scene) {
    reset_world(); DescWrites d; u64 before_mixes = snx_br_counts[SNX_BR_MIXES], before_hits = snx_br_counts[SNX_BR_HITS];
    u64 before_keys = snx_br_counts[SNX_BR_WORD_BYTES];
    for (u32 step = 0; step < 32; step++) {
        fill(&d, scene == 1); VkDescriptorSetLayout layout = 11;
        if (scene == 2) layout += step % 3; /* separate layouts alternate */
        if (scene == 3) layout += step % 13; /* bounded replacement */
        if (scene == 4 && step % 4 == 0) { frame++; vk_rec_frame_reset(vk_frame_slot()); }
        if (scene == 5 && step == 0) advance_on_create = 1;
        if (scene >= 6 && scene <= 15) {
            u32 changed = step % 2;
            switch (scene) {
            case 6: d.bi[0].buffer += changed; break;
            case 7: d.bi[0].offset += changed * 256; break;
            case 8: d.bi[0].range += changed * 16; break;
            case 9: d.ii[1].imageView += changed; break;
            case 10: d.ii[1].sampler += changed; break;
            case 11: d.ii[1].imageLayout += changed; break;
            case 12: d.w[0].dstArrayElement = changed; break;
            case 13: d.w[0].dstBinding += changed; break;
            case 14: d.w[0].descriptorType += changed; break;
            case 15: d.n -= changed; break;
            }
        }
        if (scene == 16) d.n = 0;
        if (scene == 17) d.w[1].pNext = &frame; /* original synchronous path */
        if (scene == 18) d.w[1].descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE;
        VkBufferView texel = 0x445 + step % 2;
        if (scene == 19) d.w[2] = (VkWriteDescriptorSet){.sType = 35, .dstBinding = 108, .descriptorCount = 1, .descriptorType = 4, .pTexelBufferView = &texel};
        VkDescriptorBufferInfo other_bi = d.bi[0];
        VkDescriptorImageInfo other_ii[2]; memset(other_ii, (step & 1) ? 0x11 : 0x77, sizeof other_ii);
        for (u32 i = 0; i < 2; i++) {
            other_ii[i].sampler = d.ii[1 + i].sampler; other_ii[i].imageView = d.ii[1 + i].imageView;
            other_ii[i].imageLayout = d.ii[1 + i].imageLayout;
        }
        if (scene == 20 && (step & 1)) { /* pointers/padding change, resources do not */
            d.w[0].pBufferInfo = &other_bi; d.w[1].pImageInfo = other_ii; d.w[2].pImageInfo = other_ii + 1;
        }
        if (scene == 21 && (step & 1)) { VkWriteDescriptorSet w = d.w[0]; d.w[0] = d.w[1]; d.w[1] = w; }
        if (scene == 22) { d.bi[1] = (VkDescriptorBufferInfo){102, 512, 2048}; d.w[0].descriptorCount += step & 1; }
        if (scene == 23) d.w[0].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC + (step & 1);
        if (scene == 24) d.w[0].pImageInfo = &d.ii[1]; /* irrelevant pointer: fallback */
        request(optimized, layout, &d);
        memset(&d, 0xde, sizeof d); memset(&other_bi, 0, sizeof other_bi); memset(other_ii, 0, sizeof other_ii);
        texel = 0; /* delayed recording must own its data */
    }
    drain(); assert(bindings == 32);
    Work w = {mix_calls, allocations, bindings, snx_br_counts[SNX_BR_MIXES] - before_mixes, snx_br_counts[SNX_BR_HITS] - before_hits,
              snx_br_counts[SNX_BR_WORD_BYTES] - before_keys};
    return w;
}
static void failure_case(void) {
    reset_world(); DescWrites d; fill(&d, 0); g_rec = 0;
    fail_alloc = 1; assert(!desc_set_cached(12345, &d));
    fail_alloc = 0; request(1, 12345, &d); request(1, 12345, &d); drain();
    assert(bindings == 2); g_rec = 1;
}
static void bounds_case(void) {
    DescWrites d; u64 key[SNX_BR_WORDS + 1], mixes; u32 words;
    key[SNX_BR_WORDS] = 0x12345678;
    fill(&d, 1); assert(snx_br_pack(&d, key, &words, &mixes));
    assert(words == 8 + 6 * SNX_TEX_ARRAY && mixes == 6 + 12 * SNX_TEX_ARRAY);
    d.n = SNX_VKB_END + 1; assert(!snx_br_pack(&d, key, &words, &mixes));
    fill(&d, 0); d.w[0].descriptorCount = 0xffffffffu; assert(!snx_br_pack(&d, key, &words, &mixes));
    fill(&d, 0); d.w[0].descriptorCount = 0; assert(!snx_br_pack(&d, key, &words, &mixes));
    fill(&d, 0); d.w[0].pBufferInfo = NULL; assert(!snx_br_pack(&d, key, &words, &mixes));
    assert(key[SNX_BR_WORDS] == 0x12345678);
}
int main(void) {
    int on = snx_bind_reuse_on();
    for (int async = 0; async <= 1; async++) for (int scene = 0; scene < 25; scene++) {
        g_rec = async;
        Work a = run(0, scene), b = run(1, scene);
        assert(a.bindings == b.bindings);
        assert(a.mixes == b.mixes + b.saved_mixes);
        if (!on) assert(!memcmp(&a, &b, sizeof a));
        if (on && (scene <= 2 || scene == 20)) assert(b.hits >= 26 && b.mixes < a.mixes);
        if (on && scene >= 6 && scene <= 15) assert(!b.hits && !b.key_bytes); /* changing inputs: no full-key copy */
    }
    bounds_case(); failure_case(); reset_world();
    snx_bind_reuse_report(1);
    for (u32 i = 0; i < SNX_BR_COUNT; i++) assert(!snx_br_counts[i]);
    puts("BIND_REUSE_OK scenes=50 bindings=3200 resolved_descriptors_equal=1 delayed_recorder=1 frame_lifetime=1");
    return 0;
}
