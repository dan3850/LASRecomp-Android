// Native record-format regression. No game assets or Vulkan driver required.
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "../runtime/nvn/shader_prep.h"

static const char variants[] =
#include "../runtime/nvn/shader_variants.inc"
;

// Link-only stubs: this test exercises record parsing, not the GPU backend.
bool renderer_prepare_begin(void) { return false; }
bool renderer_prepare(const ShaderRec *r, const ShaderBlob *v, const ShaderBlob *f) {
    (void)r; (void)v; (void)f; return false;
}
int renderer_prepare_pending(void) { return 0; }
void renderer_prepare_end(void) {}
size_t rt_lz4_decompress(const uint8_t *a, size_t n, uint8_t *b, size_t m) {
    (void)a; (void)n; (void)b; (void)m; return 0;
}
const char *larecomp_version(void) { return "test"; }

int main(void) {
    unsigned n = 0, graphics = 0, compute = 0;
    const char *p = variants;
    while (*p) {
        const char *e = strchr(p, '\n');
        assert(e && e > p && e - p < 2047);
        char line[2048];
        memcpy(line, p, (size_t)(e - p));
        line[e - p] = 0;
        ShaderRec rec;
        assert(shader_rec_parse(line, &rec));
        if (rec.kind == 'G') {
            ++graphics;
            assert(rec.vs && rec.fs);
            assert(rec.ncolor <= 8 && rec.nattrib <= 16 && rec.nstream <= 16);
        } else {
            assert(rec.kind == 'C');
            ++compute;
            assert(rec.vs && rec.local[0] && rec.local[1] && rec.local[2]);
        }
        char format[2048];
        shader_rec_format(&rec, format, sizeof format);
        ShaderRec roundtrip;
        assert(shader_rec_parse(format, &roundtrip));
        assert(roundtrip.kind == rec.kind && roundtrip.vs == rec.vs &&
               roundtrip.fs == rec.fs && roundtrip.nattrib == rec.nattrib);
        n++;
        p = e + 1;
    }
    assert(n > 800 && graphics > 700 && compute > 0);
    printf("shader headstart: %u records (%u graphics, %u compute) PASS\n",
           n, graphics, compute);
    return 0;
}
