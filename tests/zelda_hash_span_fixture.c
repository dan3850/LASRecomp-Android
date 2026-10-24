/* Real pinned own.c, vk_guest_peek and vk_hash are supplied by the driver.
 * Host mappings emulate the GMMU; protected owner pages catch unsafe reads.
 */
#include <assert.h>
#include <stdarg.h>
#include <sys/mman.h>
#include <unistd.h>
#include "own_actual.c"

u8* g_mem;
static u8* mirror;
static u64 arena_size, gpu_bias, peek_calls, hashed_bytes, needed, pending_at;
static int fragmented, pending_owner, pending_write;
static Own owners[32];
static unsigned checks;
#define CHECK(x) do { checks++; assert(x); } while (0)
void logf_(int level, const char* fmt, ...) { (void)level; (void)fmt; }
void fatal(const char* fmt, ...) { (void)fmt; abort(); }
void pm_lock(PMutex* m) { CHECK(!pthread_mutex_lock(&m->l)); }
void pm_unlock(PMutex* m) { CHECK(!pthread_mutex_unlock(&m->l)); }
void pc_broadcast(PCond* c) { (void)c; }
int pc_wait(PCond* c, PMutex* m, i64 ns) { (void)c; (void)m; (void)ns; abort(); }
int plat_trap_continue(u8* p, u64 n) { (void)p; (void)n; abort(); }
void plat_trap_disarm(u8* p, u64 n) { (void)p; (void)n; abort(); }
u8* plat_alias_mirror(void) { return mirror; }
int mem_pool_offset(u64 a, u64* off) { *off = a; return a < arena_size ? 0 : -1; }

static void add_owner(u64 a, u64 n) {
    CHECK(g_nown < 32);
    Own owner={.lo=a, .hi=a+n, .res=(void*)(uintptr_t)(0x1000+a), .res_off=7};
    insert_nl(first_after_nl(a), &owner);
    u64 lo = a & ~(g_page-1), hi = (a+n+g_page-1) & ~(g_page-1);
    CHECK(!mprotect(g_mem+lo, hi-lo, PROT_NONE));
}
static void reset_case(void);
void gmem_need(u64 gva, u64 size) {
    (void)gva; (void)size; needed++;
    if (pending_owner) { pending_owner=0; add_owner(pending_at, 16); }
    if (pending_write) { pending_write=0; mirror[pending_at] ^= 0x5a; }
}
u64 gmmu_run(u64 gva, u64 size, u64* cpu) {
    if (gva > arena_size || gpu_bias > arena_size-gva) return 0;
    u64 a=gva+gpu_bias;
    if (size > arena_size-a) return 0;
    *cpu=a;
    u64 left=4096-(gva&4095);
    return fragmented && size>left ? left : size;
}
u8* gmem_host(u64 gva, u64 size) {
    u64 cpu=0;
    return gmmu_run(gva,size,&cpu)==size ? g_mem+cpu : NULL;
}
u8* gmem_ptr_untracked(u64 gva, u64 size) {
    u8* p=gmem_host(gva,size);
    if (p && g_own_any) {
        u64 probe=0;
        CHECK(!own_hash((u64)(p-g_mem),size,&probe));
        own_acquire((u64)(p-g_mem),size); /* real function; must land nothing */
    }
    return p;
}
u8* gmem_ptr(u64 gva, u64 size) {
    u8* p=gmem_ptr_untracked(gva,size);
    if (p) gmem_need(gva,size);
    return p;
}

#include "hash_span.h"
#include "peek_actual.inc"
#include "hash_actual.inc"
static u64 counted_hash(const void* p, u64 n) { hashed_bytes+=n; return vk_hash(p,n); }
static void counted_peek(u64 a, void* p, u64 n) { peek_calls++; vk_guest_peek(a,p,n); }
#define vk_hash counted_hash
#define vk_guest_peek counted_peek
#define MEM_HASH_PIECE 4096u
#include "hash_baseline.inc"
#include "hash_optimized.inc"
#undef vk_hash
#undef vk_guest_peek

static void reset_case(void) {
    CHECK(!mprotect(g_mem, arena_size, PROT_READ | PROT_WRITE));
    g_nown=0; g_own_any=0; g_own=owners; g_capown=32;
    gpu_bias=0; fragmented=0; pending_owner=pending_write=0;
    peek_calls=hashed_bytes=needed=0;
    memset(snx_hash_span_counts, 0, sizeof snx_hash_span_counts);
}

static u64 compare(u64 a, u64 n, int direct) {
    snx_hash_span_on=0; peek_calls=hashed_bytes=0;
    u64 old=baseline_hash(a,n), old_peeks=peek_calls;
    CHECK(hashed_bytes==n);
    snx_hash_span_on=1; peek_calls=hashed_bytes=0;
    u64 value=optimized_hash(a,n);
    CHECK(value==old && hashed_bytes==n);
    CHECK(!own_landings());
    if (direct) CHECK(!peek_calls && old_peeks==(n+4095)/4096);
    else CHECK(peek_calls==old_peeks);
    return value;
}
int main(void) {
    arena_size=2u<<20;
    FILE* f=tmpfile(); CHECK(f && !ftruncate(fileno(f),(off_t)arena_size));
    g_mem=mmap(NULL,arena_size,PROT_READ|PROT_WRITE,MAP_SHARED,fileno(f),0);
    mirror=mmap(NULL,arena_size,PROT_READ|PROT_WRITE,MAP_SHARED,fileno(f),0);
    CHECK(g_mem!=MAP_FAILED && mirror!=MAP_FAILED);
    for (u64 i=0;i<arena_size;i++) mirror[i]=(u8)((i*17+(i>>9))&255);
    CHECK(!setenv("SNX_VK_HASH_SPAN","0",1)); snx_hash_span_init(); CHECK(!snx_hash_span_on);
    CHECK(!setenv("SNX_VK_HASH_SPAN","1",1)); snx_hash_span_init(); CHECK(snx_hash_span_on);
    CHECK(!setenv("SNX_VK_HASH_SPAN","invalid",1)); snx_hash_span_init(); CHECK(!snx_hash_span_on);
    for (g_page=4096;g_page<=16384;g_page*=4) {
        reset_case(); compare(0x10000,65536,0); /* original no-owner fast path */
        reset_case(); add_owner(0x180000,32); /* unrelated global owner */
        const u64 sizes[]={1,7,8,31,4095,4096,4097,65536,262144};
        for (unsigned i=0;i<sizeof sizes/sizeof *sizes;i++) compare(0x10000,sizes[i],1);
        u64 before=compare(0x10000,65536,1);
        for (u64 i=0;i<65536;i+=4096) {
            mirror[0x10000+i+37]^=0x5a;
            u64 after=compare(0x10000,65536,1); CHECK(after!=before); before=after;
        }
        reset_case(); add_owner(0x10800,32); compare(0x10000,65536,0);
        reset_case(); add_owner(0x10800,32); compare(0x10000,64,0); /* neighbouring bytes on trapped page */
        if (g_page==16384) {
            reset_case(); add_owner(0x12000,32); compare(0x10000,64,0); /* another 4K page, same host page */
        }
        reset_case(); add_owner(0x180000,32); fragmented=1; compare(0x10000,65536,0);
        reset_case(); add_owner(0x180000,32); gpu_bias=0x80000; compare(0x10000,65536,1);
        reset_case(); add_owner(0x180000,32); gpu_bias=0x80000; add_owner(0x90040,16); compare(0x10000,65536,0);
        reset_case(); add_owner(0x180000,32); pending_at=0x10020; pending_owner=1;
        u64 expected=baseline_hash(0x10000,8192);
        reset_case(); add_owner(0x180000,32); pending_at=0x10020; pending_owner=1;
        snx_hash_span_on=1; CHECK(optimized_hash(0x10000,8192)==expected);
        CHECK(snx_hash_span_counts[3]==1 && !snx_hash_span_counts[1] && !own_landings());
        reset_case(); add_owner(0x180000,32); pending_at=0x10020; pending_write=1;
        u8 original=mirror[pending_at]; expected=baseline_hash(0x10000,8192);
        mirror[pending_at]=original;
        reset_case(); add_owner(0x180000,32); pending_at=0x10020; pending_write=1;
        snx_hash_span_on=1; CHECK(optimized_hash(0x10000,8192)==expected);
        CHECK(snx_hash_span_counts[1]==1 && !own_landings());
        snx_hash_span_report(1); CHECK(!snx_hash_span_counts[0] && !snx_hash_span_counts[2]);
    }
    reset_case(); CHECK(!munmap(g_mem,arena_size) && !munmap(mirror,arena_size)); fclose(f);
    printf("HASH_SPAN_OK checks=%u all_bytes_hashed=1 gpu_landings=0\n",checks);
    return 0;
}
