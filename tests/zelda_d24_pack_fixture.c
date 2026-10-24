/* Actual flush eligibility and production D24 recorder with byte/ordering endpoints. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned VkCommandBuffer, VkImageLayout;
typedef u64 VkPipelineStageFlags2, VkAccessFlags2;
typedef struct {u8 data[65536];} Buffer;
typedef Buffer* VkBuffer;
typedef struct {VkBuffer buf;u64 size;} VkOwnRes;
typedef struct {u32 d[512];u8 s[512];} Image;
typedef Image* VkImage;
/* Match Vulkan's C definition for the pointer handles modeled above.
 * An enum-valued zero triggers Clang's non-literal-null conversion warning. */
#define VK_NULL_HANDLE ((void*)0)
enum {VK_LRU_RT = 0, LRU_AGED = 1,
      VK_FORMAT_D24_UNORM_S8_UINT = 129, VK_IMAGE_LAYOUT_UNDEFINED = 0,
      VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL = 2, VK_PIPELINE_STAGE_2_COPY_BIT = 4,
      VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT = 8, VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT = 16,
      VK_ACCESS_2_TRANSFER_READ_BIT = 1, VK_ACCESS_2_TRANSFER_WRITE_BIT = 2,
      VK_ACCESS_2_SHADER_STORAGE_READ_BIT = 4, VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT = 8,
      VK_IMAGE_ASPECT_DEPTH_BIT = 1, VK_IMAGE_ASPECT_STENCIL_BIT = 2,
      VK_STRUCTURE_TYPE_MEMORY_BARRIER_2 = 1, VK_STRUCTURE_TYPE_DEPENDENCY_INFO = 2};
typedef struct {int sType;u64 srcStageMask,srcAccessMask,dstStageMask,dstAccessMask;} VkMemoryBarrier2;
typedef struct {int sType;u32 memoryBarrierCount;const VkMemoryBarrier2* pMemoryBarriers;} VkDependencyInfo;
typedef struct {u32 aspectMask,mipLevel,baseArrayLayer,layerCount;} Subresource;
typedef struct {u32 width,height,depth;} Extent;
typedef struct {u64 bufferOffset;u32 bufferRowLength,bufferImageHeight;Subresource imageSubresource;Extent imageExtent;} VkBufferImageCopy;
typedef struct {u32 row_bytes,h,bh,bd,y0,rows,z0,slices,lin_pitch;} VkBlMove;
typedef struct {u32 vk,bpp;int depth,stencil,raw;} Fmt;
typedef struct Surf {VkImage img;Fmt f;u32 is_rt,fkey,w,h,sw,sh,levels,layers,volume,bd,bl,bh,pitch;
                     VkImageLayout layout;u64 gva;u32 wgen,mem_wgen;u64 stage,access,wseq,gw;struct Surf* lru_next;} Surf;
static struct {Surf* head;} g_lru[2];
static struct {u64 alloc_cap;struct {struct {u32 maxStorageBufferRange,maxComputeWorkGroupCount[3];
                                           u64 minStorageBufferOffsetAlignment;} limits;} props;} g_vk;
static int snx_perf_on=1;
static u32 g_vk_present=7;
static u32 g_vk_surf_epoch=1;
static unsigned used,phase,copies,packed,bl_moves,row_copies;
static int scratch_fail,pack_fail,move_fail,shader_supported=1;
static int memory_dirty;
static Buffer output;
#define LOG(...) printf(__VA_ARGS__)
#define WARN(...) printf(__VA_ARGS__)
#include "block_offsets_actual.inc"
static u64 rt_bytes(const Surf* s) {
    return s->bl ? ((u64)s->w*4+63)/64 * (((u64)s->h+(8u<<s->bh)-1)/(8u<<s->bh)) * (512u<<s->bh)
                 : (u64)s->w*s->h*4;
}
static int moves_scaled(const Surf* s) {(void)s;return 1;}
static int depth_copies_raw(const Surf* s) {(void)s;return 0;}
static void fatal(const char* fmt,...) {(void)fmt;abort();}
static int gpu_mem_dirty_since(u64 since,u64 addr,u64 size) {assert(since==1&&addr==0x123000&&size);return memory_dirty;}
static VkBlMove rt_bl_move(const Surf* s,u32 pitch) {return (VkBlMove){s->w*4,s->h,s->bh,0,0,s->h,0,1,pitch};}
static int vk_tc_d24_pack_supported(void) {return shader_supported;}
static VkOwnRes* vk_own_res_new(u64 n) {
    used++;if(scratch_fail)return NULL;
    VkOwnRes* r=calloc(1,sizeof*r);assert(r);r->buf=malloc(sizeof(Buffer));assert(r->buf);r->size=n;return r;
}
static void vk_own_res_unref(VkOwnRes* r) {free(r->buf);free(r);}
static void vk_surf_use(VkCommandBuffer cb,Surf* s,VkImageLayout l,u64 stage,u64 access) {
    assert(cb==1);s->layout=l;s->stage=stage;s->access=access;
}
static void rec_CmdPipelineBarrier2(VkCommandBuffer cb,const VkDependencyInfo* d) {
    assert(cb==1&&phase==0&&d->memoryBarrierCount==1);
    assert(d->pMemoryBarriers->dstStageMask==VK_PIPELINE_STAGE_2_COPY_BIT);
    assert(d->pMemoryBarriers->dstAccessMask==VK_ACCESS_2_TRANSFER_WRITE_BIT);
    assert(d->pMemoryBarriers->srcStageMask&VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT);
}
static void rec_CmdCopyImageToBuffer(VkCommandBuffer cb,VkImage img,VkImageLayout l,VkBuffer b,u32 n,const VkBufferImageCopy* c) {
    assert(cb==1&&l==2&&n==2&&phase==0);copies++;
    assert(c[0].imageSubresource.aspectMask==1&&c[1].imageSubresource.aspectMask==2);
    for(unsigned i=0;i<2;i++) {
        assert(!c[i].imageSubresource.mipLevel&&!c[i].imageSubresource.baseArrayLayer&&c[i].imageSubresource.layerCount==1);
        for(u32 y=0;y<c[i].imageExtent.height;y++)for(u32 x=0;x<c[i].imageExtent.width;x++) {
            u32 at=y*c[i].bufferRowLength+x;
            if(i) b->data[c[i].bufferOffset+at]=img->s[y*c[i].imageExtent.width+x];
            else memcpy(b->data+c[i].bufferOffset+at*4,&img->d[y*c[i].imageExtent.width+x],4);
        }
    }
    phase=1;
}
static void vk_bl_barrier(VkCommandBuffer cb,int before) {
    assert(cb==1);
    if(before){assert(phase==0||phase==1||phase==3);phase=2;}
    else {assert(phase==2);phase=3;}
}
static int vk_tc_pack_d24(VkCommandBuffer cb,u32 z24,u32 w,u32 h,VkBuffer in,u64 d,u32 dp,u64 st,u32 sp,
                          VkBuffer out,u64 at,u32 op) {
    assert(cb==1&&phase==2&&in==out&&at>=st+(u64)sp*h);packed++;
    if(pack_fail)return 0;
    for(u32 y=0;y<h;y++)for(u32 x=0;x<w;x++) {
        u32 depth;memcpy(&depth,in->data+d+y*dp+x*4,4);depth&=0xffffff;
        u32 stencil=in->data[st+y*sp+x],v=z24?(depth<<8)|stencil:depth|stencil<<24;
        memcpy(out->data+at+y*op+x*4,&v,4);
    }
    return 1;
}
static int vk_bl_move(VkCommandBuffer cb,const VkBlMove* m,int to_bl,VkBuffer out,u64 off,VkBuffer in,u64 at) {
    assert(cb==1&&phase==2&&to_bl==1);bl_moves++;
    if(move_fail)return 0;
    for(u32 y=0;y<m->h;y++)for(u32 x=0;x<m->row_bytes;x++)
        out->data[off+bl_offset(x,y,0,m->row_bytes,m->h,m->bh,0)]=in->data[at+y*m->lin_pitch+x];
    return 1;
}
static void vk_copy_rows(VkCommandBuffer cb,VkBuffer in,u64 at,u32 ip,VkBuffer out,u64 off,u32 op,u32 row,u32 h) {
    assert(cb==1&&(phase==0||phase==3));row_copies++;phase=3;
    for(u32 y=0;y<h;y++)memcpy(out->data+off+y*op,in->data+at+y*ip,row);
}
#include "d24_pack.h"
#include "flush_bytes_actual.inc"
#include "pending_actual.inc"
int main(void) {
    g_vk.alloc_cap=65536;g_vk.props.limits.maxStorageBufferRange=65536;
    g_vk.props.limits.minStorageBufferOffsetAlignment=256;
    g_vk.props.limits.maxComputeWorkGroupCount[0]=g_vk.props.limits.maxComputeWorkGroupCount[1]=65535;
    Image img;for(u32 i=0;i<512;i++){img.d[i]=0xaa000000|(i*337u&0xffffff);img.s[i]=(u8)(i*11u);}
    Surf s={.img=&img,.f={129,4,1,1,0},.is_rt=1,.fkey=0x10014,.w=20,.h=9,.sw=20,.sh=9,
            .levels=1,.layers=1,.layout=4,.gva=0x123000,.wgen=4,.wseq=4,.gw=1,.bl=1,.bh=1};
    unsetenv("SNX_VK_D24_PACK");snx_d24_pack_init();assert(!snx_d24_pack_eligible(&s)&&!flush_bytes(&s)&&!used);
    setenv("SNX_VK_D24_PACK","1",1);shader_supported=0;snx_d24_pack_init();assert(!snx_d24_pack_on);
    shader_supported=1;snx_d24_pack_init();assert(snx_d24_pack_on&&!flush_bytes(&s));
    assert(snx_d24_pack_pending(&s,s.gva,rt_bytes(&s)));
    memory_dirty=1;assert(!snx_d24_pack_pending(&s,s.gva,rt_bytes(&s)));memory_dirty=0;
    assert(!snx_d24_pack_pending(&s,s.gva+16,rt_bytes(&s)));
    Surf raw=s;raw.f.depth=0;raw.f.raw=1;raw.wseq=1;raw.lru_next=&s;s.lru_next=NULL;g_lru[0].head=&raw;
    Surf *local[16],**list;u32 count=rt_pending_over(s.gva,rt_bytes(&s),local,16,&list,0);
    assert(count==1&&list[0]==&raw); // CPU before-write/readback still excludes D24.
    count=rt_pending_over(s.gva,rt_bytes(&s),local,16,&list,1);
    assert(count==2&&list[0]==&raw&&list[1]==&s); // color/depth retain common image write order.
    memory_dirty=1;count=rt_pending_over(s.gva,rt_bytes(&s),local,16,&list,1);
    assert(count==1&&list[0]==&raw);memory_dirty=0; // newer owned memory cannot be overwritten by stale depth.
    for(u32 linear=0;linear<2;linear++)for(u32 fmt=0x14;fmt<=0x16;fmt+=2) {
        s.bl=!linear;s.fkey=0x10000|fmt;s.pitch=80;s.wseq++;memset(&output,0x5a,sizeof output);
        u8 expected[sizeof output];memset(expected,0x5a,sizeof expected);
        for(u32 y=0;y<s.h;y++)for(u32 x=0;x<s.w;x++) {
            u32 d=img.d[y*s.w+x]&0xffffff,st=img.s[y*s.w+x],v=fmt==0x14?(d<<8)|st:d|st<<24;
            u64 at=linear?(u64)(y*s.w+x)*4:bl_offset(x*4,y,0,s.w*4,s.h,s.bh,0);
            memcpy(expected+at+32,&v,4);
        }
        phase=0;assert(snx_d24_pack_record(1,&s,&output,32));assert(phase==3);
        assert(!memcmp(expected,&output,sizeof output)); // includes every padding byte
    }
    assert(copies==4&&packed==4&&bl_moves==2&&row_copies==2);
    unsigned packed_before=packed;
    phase=0;assert(snx_d24_pack_record(1,&s,&output,32));assert(packed==packed_before&&snx_d24_reused==1);
    s.wgen++;s.wseq++;phase=0;assert(snx_d24_pack_record(1,&s,&output,32));assert(packed==++packed_before);
    g_vk_surf_epoch++;phase=0;assert(snx_d24_pack_record(1,&s,&output,32));assert(packed==++packed_before);
    assert(used==1); // no shared scratch request and no allocation for unchanged exports.
    Surf good=s;
    s.fkey=0x10015;assert(!snx_d24_pack_eligible(&s));s=good;
    s.sw++;assert(!snx_d24_pack_eligible(&s));s=good;
    s.layers=2;assert(!snx_d24_pack_eligible(&s));s=good;
    s.pitch++;assert(!snx_d24_pack_eligible(&s));s=good;
    s.bl=1;s.w=s.sw=17;assert(!snx_d24_pack_eligible(&s));s=good;
    s.layout=0;assert(!snx_d24_pack_eligible(&s));s=good;
    g_vk.alloc_cap=1;assert(!snx_d24_pack_eligible(&s));g_vk.alloc_cap=65536;
    unsigned before_alignment=copies;
    assert(!snx_d24_pack_record(1,&s,&output,33)&&copies==before_alignment);
    unsigned was=copies;u64 capacity=snx_d24_work->size;snx_d24_work->size=0;
    scratch_fail=1;phase=0;assert(!snx_d24_pack_record(1,&s,&output,32)&&copies==was);scratch_fail=0;snx_d24_work->size=capacity;
    pack_fail=1;snx_d24_cache.valid=0;phase=0;assert(!snx_d24_pack_record(1,&s,&output,32));pack_fail=0;
    s.bl=1;move_fail=1;phase=0;assert(!snx_d24_pack_record(1,&s,&output,32));move_fail=0;
    assert(snx_d24_failures==4);snx_d24_pack_report(1);assert(!snx_d24_packed&&!snx_d24_failures);
    vk_own_res_unref(snx_d24_work);snx_d24_work=NULL;
    puts("D24_PACK_OK off_exact=1 cpu_policy_unchanged=1 depth_stencil_exact=1 guest_padding_preserved=1 barriers_ordered=1 stale_owned_preserved=1 ordered_overlay=1 reuse_invalidated=1");
}
