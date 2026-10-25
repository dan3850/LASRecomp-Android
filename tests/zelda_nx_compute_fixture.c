/* Execute the production adapter, raw-ABI boundary and disk cache with
 * synthetic GLSL SPIR-V. Translation itself is a controlled ABI endpoint. */
#include <assert.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "nx/gpu/shader/shader.h"
typedef struct { u8 *spirv; size_t spirv_bytes; u8 *reflection_json; size_t reflection_bytes;
                 u8 *error; size_t error_bytes; } SnxRnResult;
typedef int (*SnxRnVersion)(void);
typedef void (*SnxRnFree)(SnxRnResult*);
static struct { int shader_captures; } g_settings;
static char g_cachedir[1200];
static void test_log(const char* fmt,...) {(void)fmt;}
#define LOG(...) test_log(__VA_ARGS__)
#define WARN(...) test_log(__VA_ARGS__)
#define LOG_LIMIT(n,...) test_log(__VA_ARGS__)
int snx_nx_compute_enabled(void);
void snx_nx_compute_init(void);
void snx_nx_compute_report(u64 window);
u32* snx_nx_compute_spirv(const u8*, u32, ShaderInfo*, size_t*, const u8*, u32);
static u64 vk_hash(const void* p, u64 n) {
    const u8* b=p;u64 h=0xcbf29ce484222325ull;
    for(u64 i=0;i<n;i++)h=(h^b[i])*0x100000001b3ull;
    return h;
}
static int snx_ryu_file_hash(const void* fn,u64* hash) {(void)fn;*hash=42;return 1;}
static void plat_mkdir(const char* p) {(void)mkdir(p,0700);}
static const char* vk_spirv_unavailable(const u32* p,size_t n) {(void)p;(void)n;return NULL;}
#include "nx_compute.h"
static u32* original_spv;
static size_t original_words;
static char* reflection;
static unsigned translations, releases;
static int reject_translation;
static void* read_file(const char* path,size_t* n) {
    FILE* f=fopen(path,"rb");assert(f);assert(!fseek(f,0,SEEK_END));long size=ftell(f);assert(size>=0);
    rewind(f);u8* data=calloc((size_t)size+1,1);assert(data);
    assert(fread(data,1,(size_t)size,f)==(size_t)size);assert(!fclose(f));*n=(size_t)size;return data;
}
static int translate(const u8* code,size_t code_bytes,const u8* job,size_t job_bytes,SnxRnResult* result) {
    assert(code_bytes==8 && code[0]==0x5a && job[job_bytes]==0);
    cJSON* parsed=cJSON_ParseWithOpts((const char*)job,NULL,1);assert(parsed);
    const cJSON* stage=cJSON_GetObjectItemCaseSensitive(parsed,"stage");
    const cJSON* c1=cJSON_GetObjectItemCaseSensitive(parsed,"c1");
    assert(cJSON_IsString(stage) && !strcmp(stage->valuestring,"cs") && cJSON_IsString(c1));
    assert(strlen(c1->valuestring)==32 && !strncmp(c1->valuestring,"a5",2));
    cJSON_Delete(parsed);translations++;
    if(reject_translation)return -2;
    result->spirv=malloc(original_words*4);assert(result->spirv);
    memcpy(result->spirv,original_spv,original_words*4);result->spirv_bytes=original_words*4;
    result->reflection_json=(u8*)strdup(reflection);assert(result->reflection_json);
    result->reflection_bytes=strlen(reflection);return 0;
}
static void release(SnxRnResult* result) {
    free(result->spirv);free(result->reflection_json);free(result->error);*result=(SnxRnResult){0};releases++;
}
static ShaderInfo launch(void) {return (ShaderInfo){.cs_local={1,1,1}};}
static void rejected(const char* json) {
    ShaderInfo si=launch(),before=si;size_t words=123;
    u32* p=snx_nx_adapt(original_spv,original_words,json,&si,&words);
    assert(!p && !memcmp(&si,&before,sizeof si) && words==123);
}
static void bad_field(const char* list,int index,const char* field,int value) {
    cJSON* root=cJSON_Parse(reflection);assert(root);
    cJSON* obj=cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(root,list),index);assert(obj);
    cJSON* v=cJSON_GetObjectItemCaseSensitive(obj,field);assert(v);cJSON_SetNumberValue(v,value);
    char* json=cJSON_PrintUnformatted(root);assert(json);rejected(json);free(json);cJSON_Delete(root);
}
int main(int argc,char** argv) {
    assert(argc==5 || argc==6);size_t n;
    original_spv=read_file(argv[1],&n);assert(!(n&3));original_words=n/4;
    reflection=read_file(argv[2],&n);
    snprintf(g_cachedir,sizeof g_cachedir,"%s/",argv[3]);
    snprintf(snx_nx_dir,sizeof snx_nx_dir,"%s",argv[3]);
    snx_nx_started=snx_nx_ready=snx_nx_disk=1;snx_nx_runtime=3;snx_nx_translator=5;
    snx_nx_translate=translate;snx_nx_free=release;
    u8 code[88]={0},c1[16];memset(c1,0xa5,sizeof c1);code[80]=0x5a;
    ShaderInfo si=launch(),before=si;size_t words=0;
    unsetenv("SNX_NX_COMPUTE");
    assert(!snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1) && !translations);
    setenv("SNX_NX_COMPUTE","1",1);
    if(argc==6) {
        /* A separate process reopens a variant saved by the cold run. */
        code[87]=1;
        u32* warm=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
        assert(warm && !translations && snx_nx_loaded==1 && si.ngbuf==3);
        free(warm);free(reflection);free(original_spv);
        puts("NX_COMPUTE_RESTART: disk entry reused without calling translator");
        return 0;
    }
    u32* out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);assert(out);
    assert(translations==1 && releases==1 && si.stage==ST_CS && si.cbuf_mask==0x11 &&
           si.ngbuf==3 && si.gbuf_wmask==6 && si.gbuf_cbuf_off[0]==0x2a0 &&
           si.gbuf_cbuf_off[1]==0x310 && si.gbuf_cbuf_off[2]==0x320);
    FILE* f=fopen(argv[4],"wb");assert(f);assert(fwrite(out,4,words,f)==words);assert(!fclose(f));free(out);
    u64 key=snx_nx_key(code,sizeof code,c1,sizeof c1,&before);
    char path[1400];assert(snx_nx_path(path,sizeof path,key));
    si=launch();out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
    assert(out && translations==1 && snx_nx_loaded==1);free(out);
    c1[15]^=1;si=launch();out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
    assert(out && translations==2);free(out);c1[15]^=1;
    code[87]^=1;si=launch();out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
    assert(out && translations==3);free(out);code[87]^=1;
    f=fopen(path,"rb+");assert(f);assert(!fseek(f,-1,SEEK_END));int last=fgetc(f);assert(last!=EOF);
    assert(!fseek(f,-1,SEEK_END));assert(fputc(last^1,f)!=EOF);assert(!fclose(f));
    si=launch();out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
    assert(out && translations==4);free(out);
    f=fopen(path,"wb");assert(f);assert(fwrite("partial",1,7,f)==7);assert(!fclose(f));
    si=launch();out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
    assert(out && translations==5);free(out);
    snx_nx_runtime++;si=launch();out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);
    assert(out && translations==6);free(out);
    /* A different launch must not load the old module. The controlled
       translator still returns LocalSize 1, so validation refuses it. */
    si=launch();si.cs_local[0]=2;ShaderInfo changed=si;
    assert(!snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1) && translations==7 &&
           !memcmp(&changed,&si,sizeof si));
    snx_nx_disk=0;reject_translation=1;si=launch();
    assert(!snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1) && translations==8 && releases==8);
    assert(!memcmp(&before,&si,sizeof si));reject_translation=0;
    out=snx_nx_compute_spirv(code,sizeof code,&si,&words,c1,sizeof c1);assert(out && translations==9);free(out);
    /* Reject malformed/unsupported reflection before changing caller state. */
    rejected("{}");bad_field("cbufs",0,"slot",8);bad_field("sbufs",0,"cb_slot",1);
    bad_field("sbufs",0,"flags",2);bad_field("sbufs",0,"cb_offset",16382);
    bad_field("sbufs",1,"binding",1);
    cJSON* root=cJSON_Parse(reflection);assert(root);
    cJSON_AddItemToArray(cJSON_GetObjectItemCaseSensitive(root,"notes"),cJSON_CreateString("guessed fact"));
    char* json=cJSON_PrintUnformatted(root);assert(json);rejected(json);free(json);cJSON_Delete(root);
    u32 saved=original_spv[5];original_spv[5]=0;rejected(reflection);original_spv[5]=saved;
    char driver[80]="legacy-driver.bin";snx_nx_driver_path(driver,sizeof driver);
    assert(!strcmp(driver,"legacy-driver.bin.nxcompute1"));
    char too_short[5]="abcd";snx_nx_driver_path(too_short,sizeof too_short);
    assert(!strcmp(too_short,"abcd") && !snx_nx_ready);
    snx_nx_compute_report(1);
    free(reflection);free(original_spv);
    puts("NX_COMPUTE: descriptor remap, C0 word offsets, C1/code/launch/chain invalidation, corruption, fallback and cache isolation passed");
    return 0;
}
