#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/vulkan/gmem.h"

int main(void) {
    const uint64_t base = 0x7240000000ull;
    GmemPlan p;
    GmemRange r[] = {{base + 0x108, 16}, {base + 0x100, 16},
                     {base + 0x101, 2}, {base + 0x118, 4},
                     {base + 0x400, 8}, {base - 1, 8},
                     {base + 0x1000, UINT64_MAX}, {base + 0x2000, 0}};
    assert(gmem_plan(&p, r, 8, base, 0x10000, 0x10000));
    assert(p.tab[GMAP_MAX * 4] == 2 && p.size == 0x24);
    assert(p.tab[0] == 0x100 && p.tab[1] == 0x1c && p.tab[2] == 0);
    assert(p.tab[4] == 0x400 && p.tab[5] == 8 && p.tab[6] == 7);
    assert(!gmem_plan(&p, r, 8, base, 0x10000, 0x20));
    assert(p.size == 0 && p.tab[GMAP_MAX * 4] == 0);
    GmemRange large = {base, 2 << 20};
    assert(gmem_plan(&p, &large, 1, base, 3 << 20, 3 << 20));
    assert(p.size == 2 << 20); // no 1 MiB omission
    uint8_t before[8] = {1,2,3,4,5,6,7,8}, after[8] = {1,9,10,4,5,11,7,8};
    uint8_t guest[8] = {77,2,3,4,5,6,7,88};
    assert(gmem_apply(guest, before, after, 8));
    const uint8_t want[8] = {77,9,10,4,5,11,7,88};
    assert(!memcmp(guest, want, 8));
    assert(!gmem_apply(guest, before, before, 8));
    assert(!memcmp(guest, want, 8));
    uint8_t old[1553] = {0}, gpu[1553] = {0}, cpu[1553];
    memset(cpu, 0x42, sizeof cpu);
    gpu[511] = 1; gpu[512] = 2; gpu[1024] = 3; gpu[1552] = 4;
    assert(gmem_apply(cpu, old, gpu, sizeof cpu));
    for (unsigned i = 0; i < sizeof cpu; ++i) assert(cpu[i] == (gpu[i] ? gpu[i] : 0x42));
    puts("GMEM: aliases, bounds, packing, >1 MiB and selective writeback PASS");
}
