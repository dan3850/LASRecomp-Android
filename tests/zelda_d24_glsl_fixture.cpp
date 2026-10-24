/* Run the actual modified conversion shader, including its old unpack paths. */
#include <cassert>
#include <cstdio>
#include <vector>
#include "glsl.hpp"
using namespace glsl;
struct Convert : glsl::Invocation {
    using uint = glsl::uint;
    uint mode, units, rows, in_pitch, out_pitch, st_pitch, in_bias, out_bias, st_bias, zfloat;
    uint remap, const_a, const_b, line_out;
    const uint* src;
    uint* dst;
    using int2 = glsl::ivec2;
#include "nx/gpu/texture/texconv_modes.glsl"
#include "nx/gpu/texture/texconv.glsl"
};
int main() {
    unsigned long long checked = 0;
    for (unsigned mode : {TC_PACK_Z24S8, TC_PACK_S8Z24}) {
        unsigned src[2], dst[1];
        Convert c{}; c.mode = mode; c.units = c.rows = c.in_pitch = c.out_pitch = c.st_pitch = 1;
        c.st_bias = 1; c.src = src; c.dst = dst;
        c.gl_GlobalInvocationID = glsl::uvec3(0, 0, 0);
        for (unsigned d = 0; d <= 0xffffffu; d++) {
            unsigned s = (d ^ (d >> 8) ^ (d >> 16)) & 255;
            src[0] = d | ((d * 73u) << 24); src[1] = s | 0xbadcde00u;
            c.main();
            unsigned expected = mode == TC_PACK_Z24S8 ? (d << 8) | s : d | (s << 24);
            assert(dst[0] == expected); checked++;
        }
        for (unsigned w : {1u, 3u, 4u, 5u, 63u, 64u, 65u, 127u}) {
            unsigned h = 3, dp = (w + 3) & ~3u, sp = (w + 3) / 4, op = dp + 4;
            unsigned db = 7, sb = db + dp * h + 5, ob = 9;
            std::vector<unsigned> in(sb + sp * h + 8, 0xcafebabe), out(ob + op * h + 11, 0x13579bdf);
            for (unsigned y = 0; y < h; y++) for (unsigned x = 0; x < w; x++) {
                in[db + y * dp + x] = (y * 997 + x * 337) | 0xff000000u;
                unsigned shift = (x & 3) * 8, s = (x * 7 + y * 13) & 255;
                auto& word = in[sb + y * sp + x / 4]; word = (word & ~(255u << shift)) | s << shift;
            }
            auto before = in;
            c.src = in.data(); c.dst = out.data(); c.units = w; c.rows = h;
            c.in_pitch = dp; c.st_pitch = sp; c.out_pitch = op; c.in_bias = db; c.st_bias = sb; c.out_bias = ob;
            for (unsigned y = 0; y < h + 1; y++) for (unsigned x = 0; x < ((w + 63) / 64) * 64; x++) {
                c.gl_GlobalInvocationID = glsl::uvec3(x, y, 0); c.main();
            }
            assert(in == before);
            for (unsigned y = 0; y < h; y++) for (unsigned x = 0; x < w; x++) {
                unsigned d = (y * 997 + x * 337) & 0xffffff, s = (x * 7 + y * 13) & 255;
                assert(out[ob + y * op + x] == (mode == TC_PACK_Z24S8 ? (d << 8) | s : d | s << 24));
            }
            for (unsigned i = 0; i < out.size(); i++) {
                bool pixel = i >= ob && i < ob + op * h && (i - ob) % op < w;
                if (!pixel) assert(out[i] == 0x13579bdf);
            }
            // Old upload conversion must recover every packed depth/stencil bit.
            std::vector<unsigned> unpack(dp * h + sp * h + 8, 0);
            Convert u{}; u.mode = mode == TC_PACK_Z24S8 ? TC_S8D24 : TC_D24S8;
            u.units = (w + 3) / 4; u.rows = h; u.in_pitch = op; u.in_bias = ob;
            u.out_pitch = dp; u.st_pitch = sp; u.st_bias = dp * h; u.src = out.data(); u.dst = unpack.data();
            for (unsigned y = 0; y < h; y++) for (unsigned x = 0; x < u.units; x++) {
                u.gl_GlobalInvocationID = glsl::uvec3(x, y, 0); u.main();
            }
            for (unsigned y = 0; y < h; y++) for (unsigned x = 0; x < w; x++) {
                assert(unpack[y * dp + x] == (in[db + y * dp + x] & 0xffffff));
                assert(((unpack[dp * h + y * sp + x / 4] >> (8 * (x & 3))) & 255) == ((x * 7 + y * 13) & 255));
            }
        }
    }
    std::printf("D24_GLSL_OK exhaustive_depths=%llu layouts=2 padding_unchanged=1 old_upload_roundtrip=1\n", checked);
}
