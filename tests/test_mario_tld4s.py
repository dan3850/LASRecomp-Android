"""Mario Maxwell TLD4S: compile the production translator with a tiny synthetic shader.

No proprietary NSO, shader binary, game cache or APK is needed or changed.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/nvn/maxwell/translate.c"
DRIVER = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "runtime/nvn/maxwell/shader.h"

static int check_shader(uint64_t word, bool glsl, bool valid,
                        const char *message, bool half, unsigned comp) {
    uint64_t program[32] = {0};
    // Maxwell graphics binary: 0x80-byte header, scheduling word, insn, EXIT.
    uint8_t *bytes = (uint8_t *)program;
    uint32_t targets = 15;
    memcpy(bytes + 0x30 + 0x48, &targets, sizeof targets);
    uint64_t *code = (uint64_t *)(bytes + 0x80);
    code[0] = 0x001f8000fc0007e0ull;
    code[1] = word;
    code[2] = 0xe30000000007000full;
    code[3] = 0xe2400fffff87000full;
    ShaderKey key = {0};
    key.glsl = glsl;
    key.vs_out_mask = 0xffffffffu;
    ShaderInfo *info = maxwell_translate(bytes, sizeof program, STAGE_FRAGMENT, &key);
    if (!info) { fprintf(stderr, "NULL info\\n"); return 1; }
    int error = 0;
    if (valid) {
        if (!info->msl || info->error[0] || info->ntex != 1 ||
            info->tex[0].handle_offset != 10 * 4 ||
            info->tex[0].type != TEXTYPE_2D ||
            info->tex[0].shadow || !strstr(info->msl, "textureGather(t0") ||
            !strstr(info->msl, "r6 =") || !strstr(info->msl, "r7 =") ||
            !strstr(info->msl, "r0 =") || !strstr(info->msl, "r1 ="))
            error = 2;
        char selector[64];
        snprintf(selector, sizeof selector, ", %u)", comp);
        if (!info->msl || !strstr(info->msl, selector)) error = 3;
        if (!info->msl || !!strstr(info->msl, "packHalf2x16") != half) error = 4;
    } else {
        if (info->msl || !strstr(info->error, message)) error = 5;
    }
    if (error)
        fprintf(stderr, "case=%016llx glsl=%d err=%d info=%s\\n",
                (unsigned long long)word, glsl, error,
                info->msl ? info->msl : info->error);
    maxwell_free(info);
    return error;
}

int main(void) {
    const uint64_t observed = 0xdf0000a000b70a06ull;
    // Mario exact failing word: TLD4S 2D, tex10, r10/r11, r6/r7/r0/r1.
    if (check_shader(observed, true, true, "", false, 0)) return 1;
    // Maxwell TLD4S.F16 uses the same gather but packs two half values
    // into each destination register.
    if (check_shader(observed | 0x0080000000000000ull,
                     true, true, "", true, 0)) return 2;
    // Component selection is a 2-bit constant at bits 52..53.
    if (check_shader(observed | (2ull << 52), true, true, "", false, 2)) return 3;
    // Complex texture variants must fail instead of fabricating values.
    if (check_shader(observed | (1ull << 51), true, false,
                     "variant not implemented", false, 0)) return 4;
    if (check_shader(observed | (1ull << 50), true, false,
                     "variant not implemented", false, 0)) return 5;
    // MSL behavior is intentionally unchanged from the reference translator.
    if (check_shader(observed, false, false,
                     "unknown instruction", false, 0)) return 6;
    return 0;
}
'''


class MarioTld4s(unittest.TestCase):
    def test_maxwell_tld4s_real_word_vulkan_glsl(self):
        cc = shutil.which("clang")
        if not cc:
            self.skipTest("clang needed for the native shader translator fixture")
        with tempfile.TemporaryDirectory(prefix="mario-tld4s-") as d:
            source = Path(d) / "tld4s.c"
            binary = Path(d) / "tld4s"
            source.write_text(DRIVER)
            cmd = [cc, "-std=gnu11", "-O0", "-I", str(ROOT),
                   str(source), str(SOURCE), "-lm", "-o", str(binary)]
            built = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
