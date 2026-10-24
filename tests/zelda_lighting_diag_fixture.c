/* Native execution of the observer, exact keys/bounds and immutable inputs. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t u64;
typedef uint32_t u32;
typedef unsigned VkImageViewType;
typedef u64 VkImageView;
#define VK_NULL_HANDLE 0
#define VK_IMAGE_VIEW_TYPE_2D 1
typedef struct { int shadow; } ShTex;
typedef struct { u64 hash; struct { u32 sph[20]; } si; } VkSh;
typedef struct { float x,y,width,height,minDepth,maxDepth; } VkViewport;
typedef struct { u64 gva; u32 w,h,sw,sh; int is_rt; struct { int vk,depth; } f; } Surf;
typedef struct { u32 ncolor,color[8],depth; struct { u32 en,sc,dc,cop,sa,da,aop,mask; } blend[8]; } PipeKey;
enum { SNX_GFX_KEY_WORDS = 14 };
typedef struct { u64 key[SNX_GFX_KEY_WORDS]; } SnxGfxKey;
static u64 snx_gfx_window = 1;
static u32 g_vk_present = 99;
static int snx_gfx_diag_on, log_calls, viewport_calls;
#define LOG(...) do { log_calls++; printf(__VA_ARGS__); } while (0)
static VkViewport vk_render_viewport(const u32* r) {
    (void)r; viewport_calls++;
    return (VkViewport){0,0,2048,2048,-1,1};
}
#include "gfx_first_actual.inc"
#include "lighting_diag.h"
int main(void) {
    VkSh vs={.hash=11}, fs={.hash=22}; fs.si.sph[18]=15;
    Surf color={.gva=0x1000,.w=1280,.h=720,.sw=1280,.sh=720,.is_rt=1,.f={.vk=122}};
    Surf depth={.gva=0x2000,.w=1280,.h=720,.f={.vk=129,.depth=1}};
    Surf* rt[8]={&color};
    PipeKey pipe={.ncolor=1,.color={122},.depth=129,.blend={{1,6,7,0,1,0,0,15}}};
    u32 r[0x1000],tic[8],tsc[8];
    for(unsigned i=0;i<0x1000;i++)r[i]=0xffffffffu;
    for(unsigned i=0;i<8;i++)tic[i]=tsc[i]=0xffffffffu;
    ShTex plain={0}, shadow={1};
    snx_lighting_init();snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);
    snx_lighting_texture(&fs,4,0,&plain,0,tic,tsc,&color,1,0,1);snx_lighting_report(1);
    assert(!log_calls && !viewport_calls && !snx_light_n && !snx_light_rt_n);
    snx_gfx_diag_on=1;snx_lighting_init();
    PipeKey original_pipe=pipe; Surf original_color=color,original_depth=depth;
    u32 original_regs[0x1000];memcpy(original_regs,r,sizeof r);
    snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);
    snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);
    assert(snx_light_n==1 && snx_light_attempts==2);
    assert(!memcmp(r,original_regs,sizeof r) && !memcmp(&pipe,&original_pipe,sizeof pipe));
    assert(!memcmp(&color,&original_color,sizeof color) && !memcmp(&depth,&original_depth,sizeof depth));
    r[0x4c7]=0x3f000000;snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);
    pipe.blend[0].sc=10;snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);
    rt[0]=NULL;rt[1]=&color;pipe.ncolor=2;pipe.color[1]=122;pipe.blend[1]=pipe.blend[0];
    snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);assert(snx_light_n==4);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,1,0,1);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,1,0,1);
    assert(snx_light_rt_n==1 && snx_light_rt_attempts==2);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,NULL,1,0,1);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&depth,1,0,1);
    snx_lighting_texture(&fs,4,2,&shadow,0,tic,tsc,&color,1,0,1);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,3,0,1);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,1,0,0);
    color.is_rt=0;snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,1,0,1);color.is_rt=1;
    assert(snx_light_rt_n==1 && snx_light_rt_attempts==2);
    snx_lighting_report(1);snx_lighting_report(2);snx_gfx_window=3;
    for(unsigned i=0;i<200;i++){
        fs.hash=1000+i;
        snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);
        snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,1,0,1);
    }
    assert(snx_light_n==64 && snx_light_rt_n==64 && !snx_light_line_refused);
    snx_lighting_report(3);assert(!snx_light_n && !snx_light_rt_n);
    snx_gfx_diag_on=0;int logs=log_calls,views=viewport_calls;
    snx_lighting_state(&vs,&fs,rt,&depth,&pipe,r);snx_lighting_init();snx_lighting_report(4);
    snx_lighting_texture(&fs,4,2,&plain,0,tic,tsc,&color,1,0,1);
    assert(log_calls==logs && viewport_calls==views);
    puts("LIGHTING_DIAG_OK off_no_work=1 inputs_immutable=1 separate_bounds=1");
}
