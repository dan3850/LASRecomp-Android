/* Synthetic Maxwell programs only; no captured game code. */
#include "nx/gpu/shader/shader.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static u64 mov32(u32 r, u32 bits) { return 0x010000000007f000ull | ((u64)bits << 20) | r; }

int main(int argc, char** argv) {
    assert(argc == 5);
    u32 mask = (u32)strtoul(argv[1], NULL, 16);
    int pair = atoi(argv[2]), subgroup = atoi(argv[3]);
    assert(mask == 0x99 || mask == 0x66 || mask == 0xa5 || mask == 0x5a);
    u64 program[24] = {0}, instructions[3];
    u32 target = 1; /* fragment output 0, red = R0 */
    memcpy((u8*)program + 18 * sizeof(u32), &target, sizeof target);
    if (pair) {
        /* IPA R2, a[0x80]; SHFL.BFLY R1, R2, axis, 0x1f (PT). */
        instructions[0] = (0xe003ff87cff7ff07ull & ~((255ull << 30) | 255ull)) | (32ull << 30) | 2;
        u32 axis = mask == 0xa5 || mask == 0x5a ? 2 : 1;
        instructions[1] = (0xef17700cf0170506ull & ~((255ull << 8) | (31ull << 20) | 255ull)) |
                          (2ull << 8) | ((u64)axis << 20) | 1;
    } else {
        instructions[0] = mov32(1, 0x41540000u); /* 13.25f */
        instructions[1] = mov32(2, 0xc0f00000u); /* -7.5f */
    }
    instructions[2] = 0x50f8000000070000ull | ((u64)mask << 28) | (2ull << 20) | (1ull << 8);
    u32 at = 10;
    for (int i = 0; i < 4; i++) {
        if ((at - 10) % 4 == 0) program[at++] = 0x001f8000fc0007e0ull;
        program[at++] = i < 3 ? instructions[i] : 0xe30000000007000full;
    }
    ShaderInfo info = {0};
    size_t words = 0;
    u32* result = shader_to_spirv((u8*)program, sizeof program, ST_FS, &info, &words, 1, 1, 1, subgroup);
    if (!subgroup) {
        assert(!result && info.unsupported && strstr(info.first_unsupported, "subgroup"));
        return 0;
    }
    if (!result) { fprintf(stderr, "%s\n", info.first_unsupported); return 1; }
    FILE* f = fopen(argv[4], "wb");
    assert(f && fwrite(result, sizeof *result, words, f) == words && !fclose(f));
    free(result);
    return 0;
}
