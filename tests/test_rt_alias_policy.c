// clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined
// tests/test_rt_alias_policy.c -o /tmp/test_rt_alias && /tmp/test_rt_alias
#include "../runtime/nvn/vulkan/rt_alias_policy.h"
#include <assert.h>

int main(void) {
    const uint32_t COLOR = 1, DEPTH = 2, STENCIL = 4;
    RtAliasDesc a = {.format=1,.width=1920,.height=1080,.aspect=COLOR,.base_type=2,
        .levels=1,.layers=1,.depth=1,.samples=1,.gpu_owned=true,.has_image=true};
    RtAliasDesc b = a;
    assert(rt_alias_compatible(a,b));
    assert(rt_alias_needed_aspects(COLOR, 0) == COLOR);
    assert(rt_alias_needed_aspects(COLOR, COLOR) == 0);
    b.width++; assert(!rt_alias_compatible(a,b)); b = a;
    b.format++; assert(!rt_alias_compatible(a,b)); b = a;
    b.levels=2; assert(!rt_alias_compatible(a,b)); b = a;
    b.layers=2; assert(!rt_alias_compatible(a,b)); b = a;
    b.samples=4; assert(!rt_alias_compatible(a,b)); b = a;
    b.presented=true; assert(!rt_alias_compatible(a,b)); b = a;
    b.gpu_owned=false; assert(!rt_alias_compatible(a,b)); b = a;
    b.aspect=DEPTH; assert(!rt_alias_compatible(a,b)); b = a;
    a.aspect = DEPTH | STENCIL; b = a;
    assert(rt_alias_compatible(a,b));
    assert(rt_alias_needed_aspects(a.aspect, DEPTH) == STENCIL);
    assert(rt_alias_needed_aspects(a.aspect, a.aspect) == 0);
    return 0;
}
