/* SPDX-License-Identifier: MIT
 * Fast lookup of complete, already resolved descriptor writes. Included after
 * snx_desc_original in render.c; resource checks and barriers precede it.
 */
#ifndef SNX_BIND_REUSE_H
#define SNX_BIND_REUSE_H
enum { SNX_BR_SLOTS = 10, SNX_BR_WORDS = 7 * SNX_VKB_END + 6 * SNX_TEX_ARRAY };
enum { SNX_BR_CALLS, SNX_BR_HITS, SNX_BR_ORIGINAL, SNX_BR_UNSUPPORTED,
       SNX_BR_WORD_BYTES, SNX_BR_MIXES, SNX_BR_SAVED, SNX_BR_COUNT };
static u64 snx_br_counts[SNX_BR_COUNT]; /* all calls under vk_lock */
typedef struct {
    VkDescriptorSetLayout layout;
    VkDescriptorSet set;
    u64 frame;
    u32 words, ready;
    u64 key[SNX_BR_WORDS];
} SnxBrState;
static SnxBrState snx_br_states[SNX_BR_SLOTS];
static u32 snx_br_replace;
int snx_bind_reuse_on(void) {
    static int mode = -1;
    if (mode < 0) {
        const char* e = getenv("SNX_VK_BIND_REUSE");
        mode = e && !strcmp(e, "1");
        LOG("SNX_BIND_REUSE_META_V1 {\"enabled\":%d,\"slots\":%u,\"max_key_bytes\":%u,\"resolved_checks\":1}\n",
            mode, SNX_BR_SLOTS, (unsigned)(SNX_BR_WORDS * sizeof(u64)));
    }
    return mode;
}
/* Explicit fields, excluding padding and temporary pointer addresses. Unknown
 * extension/type/pointer combinations fall back to the existing cache. */
static int snx_br_walk(const DescWrites* d, u64* key, u32 limit, int compare, u32* words, u64* mixes) {
    u32 n = 0;
    u64 descriptors = 0;
    if (d->n > SNX_VKB_END) return -1;
#define SNX_BR_WORD(value) do { u64 v = (value); \
    if (compare) { if (n >= limit || key[n] != v) return 0; } else key[n] = v; \
    n++; } while (0)
    for (u32 i = 0; i < d->n; i++) {
        const VkWriteDescriptorSet* w = &d->w[i];
        if (w->pNext || w->sType != VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET ||
            !w->descriptorCount || n > SNX_BR_WORDS - 4 ||
            w->descriptorCount > (SNX_BR_WORDS - n - 4) / 3) return -1;
        int kind;
        switch (w->descriptorType) {
        case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER:
        case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER:
        case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC:
        case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC:
            kind = 0; if (!w->pBufferInfo || w->pImageInfo || w->pTexelBufferView) return -1; break;
        case VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:
        case VK_DESCRIPTOR_TYPE_STORAGE_IMAGE:
            kind = 1; if (!w->pImageInfo || w->pBufferInfo || w->pTexelBufferView) return -1; break;
        case VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER:
        case VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER:
            kind = 2; if (!w->pTexelBufferView || w->pBufferInfo || w->pImageInfo) return -1; break;
        default: return -1;
        }
        SNX_BR_WORD(w->dstBinding);
        SNX_BR_WORD(w->descriptorType);
        SNX_BR_WORD(w->descriptorCount);
        SNX_BR_WORD(w->dstArrayElement);
        for (u32 j = 0; j < w->descriptorCount; j++) {
            if (!kind) {
                SNX_BR_WORD((u64)(uintptr_t)w->pBufferInfo[j].buffer);
                SNX_BR_WORD(w->pBufferInfo[j].offset);
                SNX_BR_WORD(w->pBufferInfo[j].range);
            } else if (kind == 1) {
                SNX_BR_WORD((u64)(uintptr_t)w->pImageInfo[j].imageView);
                SNX_BR_WORD((u64)(uintptr_t)w->pImageInfo[j].sampler);
                SNX_BR_WORD((u64)w->pImageInfo[j].imageLayout);
            } else {
                SNX_BR_WORD((u64)(uintptr_t)w->pTexelBufferView[j]);
                SNX_BR_WORD(0); SNX_BR_WORD(0);
            }
        }
        descriptors += w->descriptorCount;
    }
    if (compare && n != limit) return 0;
    *words = n;
    *mixes = 2 + 2 * (u64)d->n + 6 * descriptors; /* exact old dset_mix call count */
    return 1;
#undef SNX_BR_WORD
}
static int snx_br_pack(const DescWrites* d, u64* key, u32* words, u64* mixes) {
    return snx_br_walk(d, key, 0, 0, words, mixes) > 0;
}
static VkDescriptorSet desc_set_cached(VkDescriptorSetLayout layout, DescWrites* d) {
    if (!snx_bind_reuse_on()) return snx_desc_original(layout, d);
    snx_br_counts[SNX_BR_CALLS]++;
    u32 words;
    u64 mixes, frame = vk_frame_id() + 1;
    if (!layout) {
        snx_br_counts[SNX_BR_ORIGINAL]++;
        return snx_desc_original(layout, d);
    }
    u32 slot = SNX_BR_SLOTS;
    for (u32 i = 0; i < SNX_BR_SLOTS; i++)
        if (snx_br_states[i].layout == layout) { slot = i; break; }
    if (slot < SNX_BR_SLOTS) {
        SnxBrState* s = &snx_br_states[slot];
        if (s->set && s->frame == frame && s->ready) {
            int match = snx_br_walk(d, s->key, s->words, 1, &words, &mixes);
            if (match > 0) {
                snx_br_counts[SNX_BR_HITS]++;
                snx_br_counts[SNX_BR_MIXES] += mixes;
                g_vk_dset_reused++;
                return s->set;
            }
            if (match < 0) snx_br_counts[SNX_BR_UNSUPPORTED]++;
        }
    } else {
        for (u32 i = 0; i < SNX_BR_SLOTS; i++)
            if (snx_br_states[i].frame != frame) { slot = i; break; }
        if (slot == SNX_BR_SLOTS) slot = snx_br_replace++ % SNX_BR_SLOTS;
    }
    snx_br_counts[SNX_BR_ORIGINAL]++;
    VkDescriptorSet set = snx_desc_original(layout, d);
    /* Creation can start/recycle a frame. Do not retain an old-frame key under
       a newer frame's lifetime, nor cache a failed allocation. */
    if (set && frame == vk_frame_id() + 1) {
        SnxBrState* s = &snx_br_states[slot];
        /* Only build a full key after two consecutive original lookups of this
           layout return the same set. Changing uniforms then pay no key copy. */
        if (s->layout == layout && s->set == set && s->frame == frame) {
            s->ready = 0;
            if (snx_br_pack(d, s->key, &words, &mixes)) {
                s->words = words; s->ready = 1;
                snx_br_counts[SNX_BR_WORD_BYTES] += (u64)words * sizeof(u64);
                snx_br_counts[SNX_BR_SAVED]++;
            } else snx_br_counts[SNX_BR_UNSUPPORTED]++;
        } else {
            s->layout = layout; s->set = set; s->frame = frame; s->words = 0; s->ready = 0;
        }
    }
    return set;
}
void snx_bind_reuse_report(u64 window) {
    LOG("SNX_BIND_REUSE_V1 {\"window\":%llu,\"enabled\":%d,\"lookups\":%llu,\"fast_hits\":%llu,"
        "\"original_lookups\":%llu,\"key_refusals\":%llu,\"key_bytes_built\":%llu,"
        "\"hash_mix_calls_bypassed\":%llu,\"states_saved\":%llu}\n",
        (unsigned long long)window, snx_bind_reuse_on(),
        (unsigned long long)snx_br_counts[SNX_BR_CALLS], (unsigned long long)snx_br_counts[SNX_BR_HITS],
        (unsigned long long)snx_br_counts[SNX_BR_ORIGINAL], (unsigned long long)snx_br_counts[SNX_BR_UNSUPPORTED],
        (unsigned long long)snx_br_counts[SNX_BR_WORD_BYTES], (unsigned long long)snx_br_counts[SNX_BR_MIXES],
        (unsigned long long)snx_br_counts[SNX_BR_SAVED]);
    memset(snx_br_counts, 0, sizeof snx_br_counts);
}
#endif
