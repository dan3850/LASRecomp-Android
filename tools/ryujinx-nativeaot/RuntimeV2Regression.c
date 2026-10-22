/* SPDX-License-Identifier: MIT */
/* The actual callback/cache and support writer, against synthetic guest memory. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
typedef u64 VkBuffer;
#define ST_FS 4
#define SH_MAXTEX 64
#define WARN_LIMIT(n, ...) ((void)0)
#define WARN(...) ((void)0)
#define LOG(...) ((void)0)
#define fatal(...) abort()
typedef struct {u32 cbuf_off; u8 type,array,shadow,bindless,bl_cbuf,bl2,bl2_cbuf,flags;u32 bl2_off;} ShTex;
typedef struct {int stage;u32 sph[20],cbuf_mask,cbuf_max[18],in_mask,out_mask;
    int ntex,nimg,ngbuf,unsupported;char first_unsupported[96];ShTex tex[64];
    u64 tex_int_mask,tex_dc_color_mask;u32 rt_int_mask,in_unfed_mask,early_fragment_tests;} ShaderInfo;
typedef struct {void* ryu_facts;int ryujinx;u64 hash;ShaderInfo si;} VkSh;
typedef struct {u32 r3d[4096];} Channel;
static Channel channel, *g_sh_ch = &channel;
static u32 cbuf[18][512], memory[1024];
static int sh_cb_read(u32 idx,u32 off,u32* out) {
    if (idx >= 18 || off >= 2048 || (off & 3)) return 0;
    *out = cbuf[idx][off/4]; return 1;
}
static void gmem_read(u64 addr,void* dst,size_t n) {assert(addr+n <= sizeof memory);memcpy(dst,(u8*)memory+addr,n);}
static const char* vk_spirv_unavailable(const u32* spv,size_t n) {(void)spv;(void)n;return NULL;}
#include "scarlet_runtime_v2.h"
static u64 submission = 1, next_offset;
static u8 staging[10000]; static unsigned allocations;
static u64 vk_submit_number(void) {return submission;}
static u64 vk_stage_align(void) {return 16;}
static u8* vk_stage(size_t size,u64 align,VkBuffer* b,u64* off) {
    (void)align; *b = 8; *off = next_offset;next_offset += size;allocations++;assert(next_offset <= sizeof staging);return staging+*off;
}
#include "scarlet_support_v2.h"
int main(void) {
    assert(sizeof(SnxRnMetaV2)==2072);
    assert(snx_rn_backend_key(0)==0 && snx_rn_backend_key(1)==1);
    assert(vk_shader_native_scope(1)==0 && snx_rn_backend_key(1)==0x80000001u);
    setenv("SNX_RYUJINX_NATIVE_PROBE","1",1);
    VkSh forced={0};size_t words=0;u8 code[88]={0};
    assert(snx_rn_try_v2(code,sizeof code,ST_FS,&forced,&words)==NULL);
    unsetenv("SNX_RYUJINX_NATIVE_PROBE");
    assert(vk_shader_native_scope(0)==1 && snx_rn_backend_key(1)==1);
    channel.r3d[0x982] = 2; channel.r3d[0x55E] = 128;channel.r3d[0x55F] = 10;
    u32* tic = memory + (128+3*32)/4; tic[4] = 1u<<23;tic[5] = 1u<<31;
    cbuf[2][94] = 3; cbuf[2][352] = 7u<<20;
    u32 handle = (1u<<28)|(352u<<14)|94, value;
    assert(snx_rn_query_value(1,handle,0x30002,&value) && value==3);
    assert(snx_rn_query_value(2,handle,0x30002,&value) && value==1);
    SnxRnFacts facts = {0}; VkSh shader = {.ryu_facts=&facts};snx_rn_recording=&facts;
    assert(snx_rn_query_v2(5,0,0,&value) && value==2);snx_rn_recording=NULL;
    assert(snx_rn_facts_hold(&shader));channel.r3d[0x982]=3;
    assert(!snx_rn_facts_hold(&shader));channel.r3d[0x982]=2;
    assert(snx_rn_facts_hold(&shader));facts=(SnxRnFacts){0};snx_rn_recording=&facts;
    assert(snx_rn_query_v2(1,handle,0x30002,&value));snx_rn_recording=NULL;
    assert(snx_rn_facts_hold(&shader)); tic[4] = 3u<<23;
    assert(!snx_rn_facts_hold(&shader));tic[4] = 1u<<23;
    assert(snx_rn_facts_hold(&shader));
    assert(snx_rn_query_value(1,94,-1,&value) && value==3); /* combined */
    cbuf[2][352]=7;
    assert(snx_rn_query_value(1,(2u<<28)|(352u<<14)|94,0x30002,&value) && value==3);
    assert(snx_rn_query_value(1,(3u<<28)|(7u<<14)|94,0x30002,&value) && value==3);
    assert(!snx_rn_query_value(0,2048,1,&value));
    facts=(SnxRnFacts){0};snx_rn_recording=&facts;cbuf[1][3]=123;
    assert(snx_rn_query_v2(0,12,1,&value) && value==123);snx_rn_recording=NULL;
    cbuf[1][3]=456;assert(!snx_rn_facts_hold(&shader));
    float scales[65];for(int i=0;i<65;i++)scales[i]=1;scales[0]=2;scales[1]=2;
    VkBuffer b;u64 off;float f;
    assert(snx_ryu_support(scales,0,&b,&off));memcpy(&f,staging+off+192,4);assert(f==2);
    assert(snx_ryu_support(scales,0,&b,&off) && allocations==1);
    scales[1]=1;assert(snx_ryu_support(scales,0,&b,&off) && allocations==2);
    memcpy(&f,staging+off+208,4);assert(f==1);
    submission++;assert(snx_ryu_support(scales,0,&b,&off) && allocations==3);
    puts("RUNTIME_V2_REGRESSIONS: handle modes, TIC/CB1 invalidation, UBO offsets/scales and submit lifetime passed");
    return 0;
}
