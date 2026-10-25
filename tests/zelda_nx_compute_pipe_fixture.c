/* The actual patched cs_pipe, with command/driver boundaries controlled.
 * Checks immutable C1 snapshots and native retry on both Vulkan failures. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nx/gpu/shader/shader.h"
typedef struct {u32 idx,off,ok,value;} VkCbRead;
typedef struct {VkCbRead* r;u32 n;} VkCbReads;
typedef int (*VkCbReader)(u32,u32,u32*);
typedef u64 VkPipeline;
typedef u64 VkShaderModule;
typedef struct {int sType;size_t codeSize;const u32* pCode;} VkShaderModuleCreateInfo;
typedef struct {int sType;struct{int sType,stage;VkShaderModule module;const char* pName;}stage;u64 layout;}VkComputePipelineCreateInfo;
enum {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO=1,VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
      VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,VK_SHADER_STAGE_COMPUTE_BIT};
static struct {int dev;struct{struct{u32 maxPerStageDescriptorStorageImages,maxDescriptorSetStorageImages;}limits;}props;}g_vk;
static u64 g_vk_playout=1;
static u8 g_cb[8][65536];static u32 g_cbn[8];
static unsigned nx_calls,native_calls,module_calls,pipe_calls;
static int nx_fail,module_fail,pipe_fail;
static void test_log(const char* fmt,...) {(void)fmt;}
#define LOG_LIMIT(n,...) test_log(__VA_ARGS__)
#define LOG(...) test_log(__VA_ARGS__)
#define WARN(...) test_log(__VA_ARGS__)
#define VK_OK(x) ((x)==0)
static int cs_cb_read(u32 idx,u32 off,u32* value) {
    if(idx>=8 || off+4>g_cbn[idx])return 0;
    memcpy(value,g_cb[idx]+off,4);return 1;
}
static u64 vk_shader_hash(const u8* code,u32 max,u32* len,VkCbReader reader) {
    (void)max;(void)reader;*len=88;return code[0];
}
static int vk_cb_reads_hold(const VkCbReads* reads,VkCbReader reader) {(void)reads;(void)reader;return 1;}
static const char* vk_corpus_dir(void) {return NULL;}
int shader_corpus_save(const char* dir,const u8* code,u32 len,u32 max,int stage,const ShaderInfo* si,u64 key) {
    (void)dir;(void)code;(void)len;(void)max;(void)stage;(void)si;(void)key;abort();
}
static u32* module_words(size_t* n) {u32* p=calloc(5,4);assert(p);p[0]=0x07230203;*n=5;return p;}
static int snx_nx_compute_enabled(void) {return 1;}
static u32* snx_nx_compute_spirv(const u8* code,u32 len,ShaderInfo* si,size_t* n,const u8* c1,u32 c1n) {
    (void)code;assert(len==88 && c1==g_cb[1] && c1n==g_cbn[1]);nx_calls++;
    if(nx_fail)return NULL;
    si->stage=ST_CS;si->ngbuf=4;si->gbuf_wmask=12;return module_words(n);
}
static u32* vk_translate_spirv(const u8* code,u32 max,int stage,ShaderInfo* si,size_t* n,
                                VkCbReader reader,VkCbReads* reads) {
    (void)code;(void)max;(void)reader;(void)reads;assert(stage==ST_CS);native_calls++;
    assert(!si->ngbuf && !si->gbuf_wmask);si->stage=stage;si->ngbuf=1;si->gbuf_wmask=1;return module_words(n);
}
static int vkCreateShaderModule(int dev,const VkShaderModuleCreateInfo* ci,const void* alloc,VkShaderModule* m) {
    (void)dev;(void)alloc;assert(ci->codeSize==20 && ci->pCode[0]==0x07230203);module_calls++;
    if(module_fail){module_fail--;return -1;}*m=module_calls;return 0;
}
static int vkCreateComputePipelines(int dev,u64 cache,int count,const VkComputePipelineCreateInfo* ci,
                                     const void* alloc,VkPipeline* p) {
    (void)dev;(void)cache;(void)alloc;assert(count==1 && ci->stage.module && !strcmp(ci->stage.pName,"main"));pipe_calls++;
    if(pipe_fail){pipe_fail--;return -1;}*p=pipe_calls;return 0;
}
static void vkDestroyShaderModule(int dev,VkShaderModule m,const void* alloc) {(void)dev;(void)m;(void)alloc;}
static u64 vk_pipeline_cache(void) {return 1;}
#include "nx_cs_pipe_actual.inc"
int main(void) {
    g_vk.props.limits.maxPerStageDescriptorStorageImages=g_vk.props.limits.maxDescriptorSetStorageImages=8;
    u8 code[88]={1};g_cbn[1]=16;g_cb[1][0]=0xa5;
    CsPipe* a=cs_pipe(code,1,1,1,0,(CsKey){0});assert(a && !a->failed && a->si.ngbuf==4 && nx_calls==1 && !native_calls);
    assert(a->nx_c1 && a->nx_c1[0]==0xa5 && cs_pipe(code,1,1,1,0,(CsKey){0})==a && nx_calls==1);
    g_cb[1][0]=0x5a;
    CsPipe* b=cs_pipe(code,1,1,1,0,(CsKey){0});assert(b!=a && nx_calls==2 && a->nx_c1[0]==0xa5 && b->nx_c1[0]==0x5a);
    g_cbn[1]=0;assert(cs_pipe(code,1,1,1,0,(CsKey){0})!=b && nx_calls==3);
    nx_fail=1;code[0]=2;g_cbn[1]=16;
    CsPipe* fallback=cs_pipe(code,1,1,1,0,(CsKey){0});assert(!fallback->failed && fallback->si.ngbuf==1 && native_calls==1);
    nx_fail=0;assert(cs_pipe(code,1,1,1,0,(CsKey){0})==fallback && nx_calls==4);
    g_cb[1][1]++;assert(cs_pipe(code,1,1,1,0,(CsKey){0})!=fallback && nx_calls==5);
    code[0]=3;module_fail=1;
    CsPipe* m=cs_pipe(code,1,1,1,0,(CsKey){0});assert(!m->failed && m->si.ngbuf==1 && native_calls==2 && !module_fail);
    code[0]=4;pipe_fail=1;
    CsPipe* p=cs_pipe(code,1,1,1,0,(CsKey){0});assert(!p->failed && p->si.ngbuf==1 && native_calls==3 && !pipe_fail);
    assert(nx_calls==7 && module_calls==9 && pipe_calls==8);
    g_nx_c1_snapshot_bytes=SNX_NX_C1_SNAPSHOT_CAP;code[0]=5;
    CsPipe* bounded=cs_pipe(code,1,1,1,0,(CsKey){0});
    assert(!bounded->failed && !bounded->nx_c1 && bounded->si.ngbuf==1 && nx_calls==7 && native_calls==4);
    g_cb[1][2]++;assert(cs_pipe(code,1,1,1,0,(CsKey){0})==bounded);
    for(int i=0;i<256;i++)while(g_csp[i]){CsPipe* next=g_csp[i]->next;free(g_csp[i]->nx_c1);free(g_csp[i]->cbr.r);free(g_csp[i]);g_csp[i]=next;}
    puts("CS_PIPE: immutable C1, full size/value invalidation, fallback retry, Vulkan module/pipeline rejection passed");
    return 0;
}
