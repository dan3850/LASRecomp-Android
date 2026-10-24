/* SPDX-License-Identifier: MIT
 * Proven prefixes of canonical uniform blocks, from immutable SPIR-V.
 * No shader rewrite, guest-write deferral, sampled checks or cache mutation.
 */
#ifndef SNX_UB_EXTENT_H
#define SNX_UB_EXTENT_H
enum { SNX_UX_REQUESTS, SNX_UX_REDUCED, SNX_UX_BEFORE, SNX_UX_AFTER, SNX_UX_COUNT };
static u64 snx_ux_counts[SNX_UX_COUNT]; /* bindings/report under vk_lock */
int snx_ub_extent_on(void) {
    static int mode = -1;
    if (mode < 0) {
        const char* e = getenv("SNX_VK_UB_EXTENT");
        mode = e && !strcmp(e, "1");
        LOG("SNX_UB_EXTENT_META_V1 {\"enabled\":%d,\"spirv_proof\":1,\"shader_unchanged\":1}\n", mode);
    }
    return mode;
}

/* IDs are local to one analysis; zero fields mean unknown. A bounded parser,
 * not a validator: malformed/unsupported layouts retain the original range. */
typedef struct {
    u32 type, kind, elem, count, storage, stride, block, offset_zero;
    u32 binding, set, binding_seen, set_seen;
    u32 constant, value;
    u32 root, span; /* root is bank + 1, span is a scalar pointer's rounded end */
} SnxUxId;
static int snx_ux_scalar(const SnxUxId* ids, u32 id, u32 bound) {
    return id && id < bound && ((ids[id].kind == 21 && ids[id].count == 32) ||
                               (ids[id].kind == 22 && ids[id].count == 32));
}
static int snx_ux_canonical(const SnxUxId* ids, u32 type, u32 bound) {
    if (!type || type >= bound || ids[type].kind != 32 || ids[type].storage != 2) return 0;
    u32 st = ids[type].elem;
    if (!st || st >= bound || ids[st].kind != 30 || ids[st].count != 1 ||
        !ids[st].block || ids[st].offset_zero != 1) return 0;
    u32 ar = ids[st].elem;
    if (!ar || ar >= bound || ids[ar].kind != 28 || ids[ar].stride != 16) return 0;
    u32 length = ids[ar].count, vec = ids[ar].elem;
    if (!length || length >= bound || !ids[length].constant || ids[length].value != 4096 ||
        !vec || vec >= bound || ids[vec].kind != 23 || ids[vec].count != 4) return 0;
    return snx_ux_scalar(ids, ids[vec].elem, bound);
}
/* Only exact 32-bit SSA constants are folded. Loads, specialization constants,
 * phi nodes, unknown expressions and dynamic indices remain unknown. */
static void snx_ux_fold(SnxUxId* ids, u32 bound, const u32* w, u32 wc, u32 op) {
    if (wc < 4 || w[1] >= bound || w[2] >= bound ||
        ids[w[1]].kind != 21 || ids[w[1]].count != 32) return;
    u32 d = w[2], a = w[3];
    if (!a || a >= bound || !ids[a].constant) return;
    u32 x = ids[a].value, y = 0, value;
    if (op == 83 || op == 124) {
        if (wc != 4 || !ids[a].type || ids[a].type >= bound ||
            ids[ids[a].type].kind != 21 || ids[ids[a].type].count != 32) return;
        value = x;
    } else {
        if (wc != 5 || !w[4] || w[4] >= bound || !ids[w[4]].constant) return;
        y = ids[w[4]].value;
        switch (op) {
        case 128: value = x + y; break;
        case 130: value = x - y; break;
        case 132: value = x * y; break;
        case 194: if (y >= 32) return; value = x >> y; break;
        case 196: if (y >= 32) return; value = x << y; break;
        case 197: value = x | y; break;
        case 198: value = x ^ y; break;
        case 199: value = x & y; break;
        default: return;
        }
    }
    ids[d].type = w[1]; ids[d].constant = 1; ids[d].value = value;
}
static void snx_ub_extent_analyze(const u32* spv, size_t words, u32 set, u32 out[18]) {
    memset(out, 0, 18 * sizeof *out);
    if (!snx_ub_extent_on() || !spv || words < 5 || words > (1u << 20) ||
        spv[0] != 0x07230203 || spv[4] || spv[3] < 2 || spv[3] > 65536) return;
    u32 bound = spv[3], seen[18] = {0}, bad[18] = {0}, extent[18] = {0}, loads[18] = {0};
    SnxUxId* ids = calloc(bound, sizeof *ids);
    if (!ids) return;
    /* Types, decorations and ordinary constants precede function bodies. */
    for (size_t at = 5; at < words;) {
        const u32* w = spv + at; u32 wc = w[0] >> 16, op = w[0] & 65535;
        if (!wc || wc > words - at) goto done;
        /* Group/ID/string decorations are outside this small proof's scope. */
        if ((op >= 73 && op <= 75) || op == 332 || op == 5632 || op == 5633) goto done;
        if (op == 21 || op == 22 || op == 23 || op == 28 || op == 30 || op == 32) {
            if (wc < 3 || !w[1] || w[1] >= bound) goto done;
            SnxUxId* d = &ids[w[1]]; d->kind = op;
            if (op == 21 || op == 22) d->count = w[2];
            else if (op == 32) { if (wc != 4) goto done; d->storage = w[2]; d->elem = w[3]; }
            else if (op == 30) { d->count = wc - 2; d->elem = w[2]; }
            else { if (wc != 4) goto done; d->elem = w[2]; d->count = w[3]; }
        } else if (op == 43) {
            if (wc < 4 || !w[1] || w[1] >= bound || !w[2] || w[2] >= bound) goto done;
            if (wc == 4 && ids[w[1]].kind == 21 && ids[w[1]].count == 32) {
                ids[w[2]].type = w[1]; ids[w[2]].constant = 1; ids[w[2]].value = w[3];
            }
        } else if (op == 59) {
            if (wc < 4 || !w[1] || w[1] >= bound || !w[2] || w[2] >= bound) goto done;
            ids[w[2]].kind = op; ids[w[2]].type = w[1]; ids[w[2]].storage = w[3];
        } else if (op == 71) {
            if (wc < 3 || !w[1] || w[1] >= bound) goto done;
            SnxUxId* d = &ids[w[1]];
            if (w[2] == 2) d->block = 1;
            if (w[2] == 6 || w[2] == 33 || w[2] == 34) {
                if (wc != 4) goto done;
                if (w[2] == 6) d->stride = w[3];
                if (w[2] == 33) { if (d->binding_seen++) goto done; d->binding = w[3]; }
                if (w[2] == 34) { if (d->set_seen++) goto done; d->set = w[3]; }
            }
        } else if (op == 72) {
            if (wc < 4 || !w[1] || w[1] >= bound) goto done;
            if (w[2] == 0 && w[3] == 35) {
                if (wc != 5 || ids[w[1]].offset_zero) goto done;
                ids[w[1]].offset_zero = w[4] ? 2 : 1;
            }
        }
        at += wc;
    }
    for (u32 i = 1; i < bound; i++) {
        SnxUxId* d = &ids[i];
        if (d->kind != 59 || d->storage != 2 || !d->binding_seen || !d->set_seen ||
            d->set != set || d->binding >= 18) continue;
        u32 b = d->binding;
        if (seen[b]++ || !snx_ux_canonical(ids, d->type, bound)) bad[b] = 1;
        d->root = b + 1;
    }
    for (size_t at = 5; at < words;) {
        const u32* w = spv + at; u32 wc = w[0] >> 16, op = w[0] & 65535;
        snx_ux_fold(ids, bound, w, wc, op);
        if ((op == 65 || op == 66) && wc >= 4 && w[3] < bound && ids[w[3]].root) {
            u32 b = ids[w[3]].root - 1;
            if (wc != 7 || !w[1] || w[1] >= bound || !w[2] || w[2] >= bound ||
                ids[w[3]].kind != 59 || !snx_ux_canonical(ids, ids[w[3]].type, bound)) bad[b] = 1;
            else {
                u32 member = w[4], index = w[5], component = w[6];
                int ok = member && member < bound && ids[member].constant && !ids[member].value &&
                         index && index < bound && ids[index].constant && ids[index].value < 4096;
                ok &= component && component < bound && ids[component].constant && ids[component].value < 4;
                u32 ptr = w[1], leaf = ids[ptr].elem;
                ok &= ids[ptr].kind == 32 && ids[ptr].storage == 2;
                ok &= snx_ux_scalar(ids, leaf, bound);
                if (!ok) bad[b] = 1;
                else {
                    ids[w[2]].root = b + 1;
                    ids[w[2]].span = (ids[index].value + 1) * 16;
                }
            }
        }
        at += wc;
    }
    /* Audit every use of each root/derived pointer. Unknown uses, escapes,
     * pointer copies/phis and whole-block loads make that bank unprovable. */
    for (size_t at = 5; at < words;) {
        const u32* w = spv + at; u32 wc = w[0] >> 16, op = w[0] & 65535;
        if (op != 5 && op != 6 && op != 15 && op != 71 && op != 72) {
            for (u32 j = 1; j < wc; j++) {
                if (!w[j] || w[j] >= bound || !ids[w[j]].root) continue;
                SnxUxId* d = &ids[w[j]]; u32 b = d->root - 1;
                if (op == 59 && j == 2) continue;
                if ((op == 65 || op == 66) && (j == 2 || j == 3)) continue;
                if (op == 61 && j == 3 && wc >= 4 && d->span) {
                    if (d->span > extent[b]) extent[b] = d->span;
                    loads[b]++;
                } else bad[b] = 1;
            }
        }
        at += wc;
    }
    for (u32 b = 0; b < 18; b++)
        if (seen[b] == 1 && !bad[b] && loads[b] && extent[b] < 65536) out[b] = extent[b];
done:
    free(ids);
}

static void snx_ub_extent_shader(const u32* spv, size_t words, VkSh* s) {
    memset(s->snx_ub_extent, 0, sizeof s->snx_ub_extent);
    if (!snx_ub_extent_on() || s->stage == ST_CS) return;
    int needed = 0;
    for (u32 b = 0; b < 18; b++)
        if ((s->si.cbuf_mask & (1u << b)) && (!s->si.cbuf_max[b] || s->si.cbuf_max[b] >= 65536)) needed = 1;
    if (needed) snx_ub_extent_analyze(spv, words, shader_vk_set(s->stage), s->snx_ub_extent);
}

u32 snx_ub_extent_len(const VkSh* s, u32 bank, u32 len) {
    if (!snx_ub_extent_on()) return len;
    u32 limit = bank < 18 ? s->snx_ub_extent[bank] : 0;
    u32 result = limit && limit < len ? limit : len;
    snx_ux_counts[SNX_UX_REQUESTS]++;
    snx_ux_counts[SNX_UX_REDUCED] += result < len;
    snx_ux_counts[SNX_UX_BEFORE] += len;
    snx_ux_counts[SNX_UX_AFTER] += result;
    return result;
}
void snx_ub_extent_report(u64 window) {
    LOG("SNX_UB_EXTENT_V1 {\"window\":%llu,\"enabled\":%d,\"bindings\":%llu,"
        "\"reduced_bindings\":%llu,\"requested_bytes\":%llu,\"bound_bytes\":%llu}\n",
        (unsigned long long)window, snx_ub_extent_on(),
        (unsigned long long)snx_ux_counts[SNX_UX_REQUESTS], (unsigned long long)snx_ux_counts[SNX_UX_REDUCED],
        (unsigned long long)snx_ux_counts[SNX_UX_BEFORE], (unsigned long long)snx_ux_counts[SNX_UX_AFTER]);
    memset(snx_ux_counts, 0, sizeof snx_ux_counts);
}
#endif
