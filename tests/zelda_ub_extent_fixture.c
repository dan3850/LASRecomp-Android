/* Synthetic Maxwell -> actual translator -> immutable SPIR-V extent proof.
 * Reuse the actual strict-buffer fixture and its delayed draw snapshots. */
#define main previous_uniform_fixture_main
#include "zelda_uniform_fixture.c"
#undef main
#include "nx/gpu/shader/shader.h"
typedef u64 VkShaderModule;
#include "cache_types_actual.inc"
static int fail_proof_alloc;
static void* proof_calloc(size_t n, size_t size) { return fail_proof_alloc ? NULL : calloc(n, size); }
#define calloc proof_calloc
#include "ub_extent.h"
#undef calloc
static struct { struct { struct { u32 maxUniformBufferRange; } limits; } props; } extent_vk;
#define g_vk extent_vk
#include "binding_size_actual.inc"
#undef g_vk
static struct { VkSh *sh, *sh_tail; u32 nsh; } g_pf;
static u64 module_hash;
static int fail_module;
static const char* vk_spirv_unavailable(const u32* spv, size_t words) { assert(spv && words >= 5); return NULL; }
static VkShaderModule vk_module_spv(const u32* spv, size_t words) {
    assert(vk_hash(spv, words * 4) == module_hash); return fail_module ? 0 : 7;
}
#include "mod_bits_actual.inc"
#include "cache_load_actual.inc"

static void cache_case(const u32* spv, size_t words, const ShaderInfo* info, u32 expected) {
    PfShader record = {.hash = 0x1234, .qh = 0x5555, .stage = ST_FS, .clen = 128, .ncbr = 1, .nspv = (u32)words, .si = *info};
    PfShader before = record;
    const u32 read[] = {1, 12, 1, 0xabcdef};
    memset(&g_pf, 0, sizeof g_pf); module_hash = vk_hash(spv, words * 4);
    assert(pf_load_shader(NULL, &record, read, spv) == 7 && g_pf.nsh == 1);
    VkSh* s = g_pf.sh; assert(s == g_pf.sh_tail && s->hash == record.hash && s->qh == record.qh);
    assert(s->snx_ub_extent[1] == (snx_ub_extent_on() ? expected : 0));
    assert(!memcmp(&record, &before, sizeof record) && !memcmp(&s->si, info, sizeof *info));
    assert(s->cbr.n == 1 && !memcmp(s->cbr.r, read, sizeof read));
    free(s->cbr.r); free(s); memset(&g_pf, 0, sizeof g_pf);
    /* Existing native extents and compute retain their current metadata path. */
    VkSh existing = {.si = *info, .stage = ST_FS}; existing.si.cbuf_max[1] = 64;
    snx_ub_extent_shader(spv, words, &existing); assert(!existing.snx_ub_extent[1]);
    existing.si = *info; existing.stage = ST_CS;
    snx_ub_extent_shader(spv, words, &existing); assert(!existing.snx_ub_extent[1]);
    fail_module = 1;
    assert(!pf_load_shader(NULL, &record, read, spv) && !g_pf.nsh && !g_pf.sh);
    fail_module = 0;
}

static u64 ldc(u32 bank, u32 offset, u32 size, u32 addr, u32 dst) {
    return 0xef90000000070000ull | ((u64)size << 48) | ((u64)bank << 36) |
           ((u64)(offset & 65535) << 20) | ((u64)addr << 8) | dst;
}
static u64 mov_imm(u32 dst, u32 value) { return 0x010000000007f000ull | ((u64)value << 20) | dst; }
static u32* translate(u32 offset, u32 size, int dynamic, int mixed, size_t* words, ShaderInfo* info) {
    u64 program[32] = {0}, insn[5];
    u32 target = 15, n = 0, at = 10;
    memcpy((u8*)program + 18 * sizeof(u32), &target, sizeof target);
    if (dynamic) insn[n++] = mov_imm(1, 0);
    insn[n++] = ldc(1, offset, size, dynamic ? 1 : 255, 0);
    if (mixed) insn[n++] = ldc(1, 1020, 4, mixed == 2 ? 1 : 255, 2);
    insn[n++] = 0xe30000000007000full;
    for (u32 i = 0; i < n; i++) {
        if ((at - 10) % 4 == 0) program[at++] = 0x001f8000fc0007e0ull;
        program[at++] = insn[i];
    }
    memset(info, 0, sizeof *info);
    u32* spv = shader_to_spirv((u8*)program, sizeof program, ST_FS, info, words, 1, 1, 1, 1);
    if (!spv) { fprintf(stderr, "translator: %s\n", info->first_unsupported); abort(); }
    assert(info->cbuf_max[1] == 65536); /* exercise the missing native extent */
    return spv;
}
static void analyze_immutable(const u32* spv, size_t words, u32 out[18]) {
    u32* copy = malloc(words * 4); assert(copy); memcpy(copy, spv, words * 4);
    snx_ub_extent_analyze(spv, words, (u32)shader_vk_set(ST_FS), out);
    assert(!memcmp(copy, spv, words * 4)); free(copy);
}
static void unknown_cases(const u32* original, size_t words) {
    u32 out[18], *spv = malloc(words * 4); assert(spv);
    snx_ub_extent_analyze(NULL, 0, 1, out); assert(!out[1]);
    fail_proof_alloc = 1;
    analyze_immutable(original, words, out); assert(!out[1]);
    fail_proof_alloc = 0;
    for (size_t n = 0; n < words; n++) {
        snx_ub_extent_analyze(original, n, 1, out);
        /* A truncated module must either keep the full range or prove only a
           complete prefix ending before an instruction boundary. Never crash. */
    }
    memcpy(spv, original, words * 4); spv[3] = 65537;
    analyze_immutable(spv, words, out); assert(!out[1]);
    memcpy(spv, original, words * 4); spv[5] &= 65535;
    analyze_immutable(spv, words, out); assert(!out[1]);
    memcpy(spv, original, words * 4); spv[0] ^= 1;
    analyze_immutable(spv, words, out); assert(!out[1]);
    snx_ub_extent_analyze(original, words, 0, out); assert(!out[1]); /* wrong descriptor set */
    for (int mode = 0; mode < 5; mode++) {
        memcpy(spv, original, words * 4);
        for (size_t at = 5; at < words; at += spv[at] >> 16) {
            u32 op = spv[at] & 65535, wc = spv[at] >> 16;
            if (mode == 0 && op == 71 && wc == 4 && spv[at + 2] == 6) { spv[at + 3] = 32; break; }
            if (mode == 1 && op == 72 && wc == 5 && spv[at + 3] == 35) { spv[at + 4] = 16; break; }
            if (mode == 2 && op == 65) { spv[at] = (wc << 16) | 67; break; } /* unsupported pointer chain */
            if (mode == 3 && op == 65) { spv[at + 5] = spv[3] - 1; break; } /* unknown index */
            if (mode == 4 && op == 65) { spv[at + 6] = spv[3] - 1; break; } /* unknown component */
        }
        analyze_immutable(spv, words, out); assert(!out[1]);
    }
    /* Copying even an unused uniform pointer is outside this proof's scope.
       Insert a valid OpCopyObject inside the function, before its return. */
    u32 ptr = 0, ptr_type = 0; size_t ret = 0;
    for (size_t at = 5; at < words; at += original[at] >> 16) {
        u32 op = original[at] & 65535;
        if (op == 65 && !ptr) { ptr_type = original[at + 1]; ptr = original[at + 2]; }
        if (op == 253) ret = at;
    }
    assert(ptr && ret);
    u32* escaped = malloc((words + 4) * 4); assert(escaped);
    memcpy(escaped, original, ret * 4);
    const u32 copied[] = {(4u << 16) | 83u, ptr_type, original[3], ptr};
    memcpy(escaped + ret, copied, sizeof copied);
    memcpy(escaped + ret + 4, original + ret, (words - ret) * 4);
    escaped[3]++;
    analyze_immutable(escaped, words + 4, out); assert(!out[1]); free(escaped);
    /* Deterministic corrupt framing/IDs/operands, also run under host ASan/UBSan. */
    u32 rng = 0x840;
    for (u32 i = 0; i < 512; i++) {
        memcpy(spv, original, words * 4);
        rng = rng * 1664525u + 1013904223u;
        spv[rng % words] ^= 1u << ((rng >> 16) & 31);
        analyze_immutable(spv, words, out);
        for (u32 b = 0; b < 18; b++) assert(!out[b] || (!(out[b] & 15) && out[b] < 65536));
    }
    free(spv);
}
static void strict_binding_case(const u32* spv, size_t words, const ShaderInfo* info, u32 expected) {
    reset_case(); VkSh shader = {.si = *info}; GpuChannel ch = {0}; VkBuffer b; u64 off;
    analyze_immutable(spv, words, shader.snx_ub_extent);
    ch.cbind[0][1] = 0x10000; ch.cbind_size[0][1] = 65536;
    extent_vk.props.limits.maxUniformBufferRange = 65536;
    u32 n = binding_size(&ch, 0, 1, &shader);
    assert(n == (snx_ub_extent_on() ? expected : 65536));
    for (int update = 0; update < 5; update++) {
        g_vk_epoch++; gpu_generation++;
        /* A small inline update, then a trailing update outside proven reads. */
        guest[0x10000 + (update & 1 ? n - 1 : 0)] ^= 0x53;
        guest[0x10000 + 65535] ^= 0x71;
        assert(cb_get(&ch, 0, 1, n, &b, &off)); remember(b, off, guest + 0x10000, n);
    }
    assert(hashes == 5 && checked_bytes == (u64)n * 5);
    assert(stages == 5 && !copy_commands && !pass_ends); /* previous uniform mode remains active */
    extent_vk.props.limits.maxUniformBufferRange = 256;
    assert(binding_size(&ch, 0, 1, &shader) <= 256);
    ch.cbind_size[0][1] = 32;
    assert(binding_size(&ch, 0, 1, &shader) <= 32);
    reset_case();
}
int main(int argc, char** argv) {
    assert(argc == 2); int on = snx_ub_extent_on();
    unsigned cases = 0;
    const u32 offsets[] = {0, 4, 12, 15, 16, 255, 1020, 16383, 32767};
    for (u32 size = 0; size <= 5; size++) for (u32 j = 0; j < sizeof offsets / sizeof *offsets; j++) {
        u32 offset = offsets[j], expected = ((offset + (size == 5 ? 4 : 0)) / 16 + 1) * 16;
        ShaderInfo info; size_t words; u32* spv = translate(offset, size, 0, 0, &words, &info), out[18], restored[18];
        analyze_immutable(spv, words, out);
        if (out[1] != (on ? expected : 0)) {
            fprintf(stderr, "extent mismatch mode=%d offset=%u size=%u got=%u expected=%u\n", on, offset, size, out[1], expected);
            abort();
        }
        /* Persist/reopen the exact module as the production cache does. */
        char path[1024]; snprintf(path, sizeof path, "%s/ldc-%u-%u.spv", argv[1], size, offset);
        FILE* f = fopen(path, "wb"); assert(f && fwrite(spv, 4, words, f) == words && !fclose(f));
        u32* disk = malloc(words * 4); assert(disk); f = fopen(path, "rb");
        assert(f && fread(disk, 4, words, f) == words && !fclose(f));
        analyze_immutable(disk, words, restored); assert(!memcmp(out, restored, sizeof out)); free(disk);
        cache_case(spv, words, &info, expected);
        strict_binding_case(spv, words, &info, expected);
        if (!cases) unknown_cases(spv, words);
        free(spv); cases++;
    }
    for (int dynamic = 0; dynamic <= 1; dynamic++) for (int mixed = 0; mixed <= 2; mixed++) {
        ShaderInfo info; size_t words; u32 out[18]; u32* spv = translate(48, 4, dynamic, mixed, &words, &info);
        analyze_immutable(spv, words, out);
        assert(out[1] == (on && !dynamic && mixed != 2 ? (mixed ? 1024u : 64u) : 0u));
        free(spv); cases++;
    }
    ShaderInfo info; size_t words; u32 out[18]; u32* spv = translate(65535, 4, 0, 0, &words, &info);
    analyze_immutable(spv, words, out); assert(!out[1]); free(spv);
    snx_ub_extent_report(1);
    for (u32 i = 0; i < SNX_UX_COUNT; i++) assert(!snx_ux_counts[i]);
    reset_case(); free(g_tmp);
    printf("UB_EXTENT_OK native_programs=%u shader_unchanged=1 strict_bytes=1 cache_reopen=1 old_draws_immutable=1\n", cases + 1);
    return 0;
}
