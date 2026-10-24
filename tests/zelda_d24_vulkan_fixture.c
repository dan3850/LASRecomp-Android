/* Standalone host Vulkan component test. No game/Android files; run with a
 * software ICD if no GPU is present. Production surface-use/TC functions and
 * pack recorder are included from generated .inc files by the test command. */
#include <vulkan/vulkan.h>
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct {VkFormat vk;u32 bpp;int depth,stencil,raw;} VkFmt;
typedef struct {VkImage img;VkFmt f;u32 is_rt,fkey,w,h,sw,sh,levels,layers,volume,bd,bl,bh,pitch;
                VkImageLayout layout;u64 gva;u32 wgen,mem_wgen;u64 wseq,gw;VkPipelineStageFlags2 stage;VkAccessFlags2 access;} Surf;
typedef struct {u32 row_bytes,height,bh,bd,y0,rows,z0,slices,lin_pitch;} VkBlMove;
static struct {VkDevice dev;VkPhysicalDeviceProperties props;u64 alloc_cap;} g_vk;
static int snx_perf_on=1;
static u32 g_vk_present=1;
static u32 g_vk_surf_epoch=1;
static VkPhysicalDevice phys;
static VkDescriptorPool desc_pool;
static VkDescriptorSetLayout g_tc_ds;
static VkPipelineLayout g_tc_layout;
static VkPipeline g_tc_pipe;
static VkDescriptorSetLayout g_bl_ds;
static VkPipelineLayout g_bl_layout;
static VkPipeline g_bl_pipe;
static u32* texconv_spv;
static u64 texconv_spv_size;
static u32* blocklinear_spv;
static u64 blocklinear_spv_size;
typedef struct {u32 runs,rows,lin_runs,y0,gob_y0,z0,bh,hmask,bd,dmask,bsh,block_row,slab,bl_bias,lin_bias,to_bl;} BlParams;
typedef struct {u32 mode,units,rows,in_pitch,out_pitch,st_pitch,in_bias,out_bias,st_bias,zfloat;
                u32 remap,const_a,const_b,line_out;} TcParams;
#define LOG(...) printf(__VA_ARGS__)
#define WARN(...) printf(__VA_ARGS__)
#define LOG_LIMIT(n,...) printf(__VA_ARGS__)
#define VK_OK(call) ((call)==VK_SUCCESS)
#define CHECK(call) do{VkResult r_=(call);if(r_){fprintf(stderr,"Vulkan error %d at %d\n",r_,__LINE__);exit(2);}}while(0)
static void fatal(const char* fmt,...) {va_list ap;va_start(ap,fmt);vfprintf(stderr,fmt,ap);va_end(ap);exit(2);}
static VkPipelineCache vk_pipeline_cache(void) {return VK_NULL_HANDLE;}
static VkDescriptorSet vk_desc_alloc(VkDescriptorSetLayout layout) {
    VkDescriptorSet set;VkDescriptorSetAllocateInfo a={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool=desc_pool,.descriptorSetCount=1,.pSetLayouts=&layout};
    CHECK(vkAllocateDescriptorSets(g_vk.dev,&a,&set));return set;
}
#define rec_CmdBindPipeline vkCmdBindPipeline
#define rec_CmdBindDescriptorSets vkCmdBindDescriptorSets
#define rec_CmdPushConstants vkCmdPushConstants
#define rec_CmdDispatch vkCmdDispatch
#define rec_CmdPipelineBarrier2 vkCmdPipelineBarrier2
#define rec_CmdCopyImageToBuffer vkCmdCopyImageToBuffer
#include "nx/gpu/texture/texconv_modes.glsl"
#include "d24_tc_actual.inc"
static void vk_render_end(void) {}
static VkImageAspectFlags vk_aspect(const VkFmt* f) {return f->depth?(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT):VK_IMAGE_ASPECT_COLOR_BIT;}
static void vk_barrier(VkCommandBuffer cb,VkImage image,u32 aspect,u64 ss,u64 sa,VkImageLayout old,
                       u64 ds,u64 da,VkImageLayout next) {
    VkImageMemoryBarrier2 b={.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2,.srcStageMask=ss,.srcAccessMask=sa,
        .dstStageMask=ds,.dstAccessMask=da,.oldLayout=old,.newLayout=next,
        .srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
        .image=image,.subresourceRange={aspect,0,1,0,1}};
    VkDependencyInfo d={.sType=VK_STRUCTURE_TYPE_DEPENDENCY_INFO,.imageMemoryBarrierCount=1,.pImageMemoryBarriers=&b};
    vkCmdPipelineBarrier2(cb,&d);
}
#include "surf_use_actual.inc"
#include "bl_barrier_actual.inc"
#include "bl_move_actual.inc"
#include "block_offsets_actual.inc"
typedef struct {VkBuffer b;VkDeviceMemory m;u64 size;u8* p;} Buffer;
typedef struct {VkBuffer buf;u64 size;Buffer allocation;} VkOwnRes;
static VkOwnRes* vk_own_res_new(u64 bytes);
static void vk_own_res_unref(VkOwnRes* r);
static int gpu_mem_dirty_since(u64 gen,u64 address,u64 bytes) {(void)gen;(void)address;(void)bytes;return 0;}
#include "rt_bl_move_actual.inc"
static u64 rt_bytes(const Surf* s) {
    u32 bh=bl_height(s->h,s->bh);
    return s->bl?((u64)s->w*4+63)/64*((s->h+(8u<<bh)-1)/(8u<<bh))*(512u<<bh):(u64)s->w*s->h*4;
}
static void vk_copy_rows(VkCommandBuffer cb,VkBuffer in,u64 at,u32 ip,VkBuffer out,u64 off,u32 op,u32 row,u32 h) {
    for(u32 y=0;y<h;y++){VkBufferCopy c={at+(u64)y*ip,off+(u64)y*op,row};vkCmdCopyBuffer(cb,in,out,1,&c);}
}
#include "d24_pack.h"
static u32 memory_type(u32 bits,VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties p;vkGetPhysicalDeviceMemoryProperties(phys,&p);
    for(u32 i=0;i<p.memoryTypeCount;i++)if((bits>>i&1)&&(p.memoryTypes[i].propertyFlags&flags)==flags)return i;
    fatal("No compatible memory type\n");return 0;
}
static Buffer buffer(u64 bytes) {
    Buffer b={.size=bytes};VkBufferCreateInfo c={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=bytes,
        .usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT|VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
    CHECK(vkCreateBuffer(g_vk.dev,&c,NULL,&b.b));VkMemoryRequirements r;vkGetBufferMemoryRequirements(g_vk.dev,b.b,&r);
    VkMemoryAllocateInfo a={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=r.size,
        .memoryTypeIndex=memory_type(r.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    CHECK(vkAllocateMemory(g_vk.dev,&a,NULL,&b.m));CHECK(vkBindBufferMemory(g_vk.dev,b.b,b.m,0));
    CHECK(vkMapMemory(g_vk.dev,b.m,0,VK_WHOLE_SIZE,0,(void**)&b.p));return b;
}
static void drop_buffer(Buffer b) {vkUnmapMemory(g_vk.dev,b.m);vkDestroyBuffer(g_vk.dev,b.b,NULL);vkFreeMemory(g_vk.dev,b.m,NULL);}
static VkOwnRes* vk_own_res_new(u64 bytes) {
    VkOwnRes* r=calloc(1,sizeof*r);assert(r);r->allocation=buffer(bytes);r->buf=r->allocation.b;r->size=bytes;return r;
}
static void vk_own_res_unref(VkOwnRes* r) {CHECK(vkDeviceWaitIdle(g_vk.dev));drop_buffer(r->allocation);free(r);}
int main(int argc,char** argv) {
    assert(argc==3);FILE* f=fopen(argv[1],"rb");assert(f);fseek(f,0,SEEK_END);texconv_spv_size=(u64)ftell(f);rewind(f);
    texconv_spv=malloc((size_t)texconv_spv_size);assert(texconv_spv&&fread(texconv_spv,1,texconv_spv_size,f)==texconv_spv_size);fclose(f);
    f=fopen(argv[2],"rb");assert(f);fseek(f,0,SEEK_END);blocklinear_spv_size=(u64)ftell(f);rewind(f);
    blocklinear_spv=malloc((size_t)blocklinear_spv_size);assert(blocklinear_spv&&fread(blocklinear_spv,1,blocklinear_spv_size,f)==blocklinear_spv_size);fclose(f);
    assert(vk_tc_d24_pack_supported());
    for(u64 i=5;i<texconv_spv_size/4;) {
        u32 words=texconv_spv[i]>>16,op=texconv_spv[i]&0xffff;
        if(op==43&&words==4&&(texconv_spv[i+3]==TC_PACK_Z24S8||texconv_spv[i+3]==TC_PACK_S8Z24)) {
            u32 saved=texconv_spv[i+3];texconv_spv[i+3]=0;
            assert(!vk_tc_d24_pack_supported());texconv_spv[i+3]=saved;
        }
        i+=words;
    }
    u32 saved=texconv_spv[5];texconv_spv[5]=0;assert(!vk_tc_d24_pack_supported());texconv_spv[5]=saved;
    VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,.apiVersion=VK_API_VERSION_1_3};
    VkInstanceCreateInfo ic={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pApplicationInfo=&app};VkInstance instance;
    CHECK(vkCreateInstance(&ic,NULL,&instance));u32 n=1;CHECK(vkEnumeratePhysicalDevices(instance,&n,&phys));assert(n);
    vkGetPhysicalDeviceProperties(phys,&g_vk.props);printf("VULKAN_COMPONENT_DEVICE %s type=%u\n",g_vk.props.deviceName,g_vk.props.deviceType);
    u32 nf=0;vkGetPhysicalDeviceQueueFamilyProperties(phys,&nf,NULL);VkQueueFamilyProperties* qs=calloc(nf,sizeof*qs);
    vkGetPhysicalDeviceQueueFamilyProperties(phys,&nf,qs);u32 family=0;while(family<nf&&!(qs[family].queueFlags&VK_QUEUE_COMPUTE_BIT))family++;assert(family<nf);free(qs);
    float priority=1;VkDeviceQueueCreateInfo qci={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,.queueFamilyIndex=family,.queueCount=1,.pQueuePriorities=&priority};
    VkPhysicalDeviceSynchronization2Features sync={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES,.synchronization2=VK_TRUE};
    VkDeviceCreateInfo dc={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.pNext=&sync,.queueCreateInfoCount=1,.pQueueCreateInfos=&qci};
    CHECK(vkCreateDevice(phys,&dc,NULL,&g_vk.dev));VkQueue queue;vkGetDeviceQueue(g_vk.dev,family,0,&queue);
    VkDescriptorPoolSize poolsize={VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,128};
    VkDescriptorPoolCreateInfo pc={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=64,.poolSizeCount=1,.pPoolSizes=&poolsize};
    CHECK(vkCreateDescriptorPool(g_vk.dev,&pc,NULL,&desc_pool));
    VkCommandPoolCreateInfo cp={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,.queueFamilyIndex=family};VkCommandPool pool;
    CHECK(vkCreateCommandPool(g_vk.dev,&cp,NULL,&pool));VkCommandBufferAllocateInfo ca={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VkCommandBuffer cb;
    CHECK(vkAllocateCommandBuffers(g_vk.dev,&ca,&cb));g_vk.alloc_cap=64ull<<20;
    setenv("SNX_VK_D24_PACK","1",1);snx_d24_pack_init();assert(snx_d24_pack_on);
    const u32 shapes[][2]={{17,9},{20,9},{64,3},{65,3},{1280,720},{1920,1080}};u64 pixels=0;
    for(unsigned shape=0;shape<6;shape++) {
        u32 w=shapes[shape][0],h=shapes[shape][1],sp=(w+3)&~3u;u64 plane=(u64)w*h*4;
        u32 maxbh=bl_height(h,4);
        u64 guest=((u64)w*4+63)/64*((h+(8u<<maxbh)-1)/(8u<<maxbh))*(512u<<maxbh);
        Buffer upload=buffer(plane+(u64)sp*h),out=buffer((guest>plane?guest:plane)+64);
        Buffer repeat=buffer(out.size),updated={0},revised={0};
        for(u32 y=0;y<h;y++)for(u32 x=0;x<w;x++) {
            u32 d=((y*w+x)*337u)&0xffffff;memcpy(upload.p+((u64)y*w+x)*4,&d,4);
            upload.p[plane+(u64)y*sp+x]=(u8)(x*11+y*37);
        }
        VkImageCreateInfo ii={.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,
            .format=VK_FORMAT_D24_UNORM_S8_UINT,.extent={w,h,1},.mipLevels=1,.arrayLayers=1,.samples=VK_SAMPLE_COUNT_1_BIT,
            .tiling=VK_IMAGE_TILING_OPTIMAL,.usage=VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT};
        Surf s={.f={129,4,1,1,0},.is_rt=1,.w=w,.h=h,.sw=w,.sh=h,.levels=1,.layers=1,.pitch=w*4,.wgen=1,.wseq=shape+1,.gva=0x123000};
        CHECK(vkCreateImage(g_vk.dev,&ii,NULL,&s.img));VkMemoryRequirements mr;vkGetImageMemoryRequirements(g_vk.dev,s.img,&mr);
        VkMemoryAllocateInfo ma={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=mr.size,.memoryTypeIndex=memory_type(mr.memoryTypeBits,0)};VkDeviceMemory im;
        CHECK(vkAllocateMemory(g_vk.dev,&ma,NULL,&im));CHECK(vkBindImageMemory(g_vk.dev,s.img,im,0));
        for(u32 fmt=0x14;fmt<=0x16;fmt+=2) for(u32 layout=0;layout<4;layout++) {
            const u32 heights[]={0,0,1,4};s.bl=layout!=0;s.bh=heights[layout];s.fkey=0x10000|fmt;
            if(s.bl&&(w&3)){assert(!snx_d24_pack_eligible(&s));continue;}
            memset(out.p,0x5a,(size_t)out.size);memset(repeat.p,0x5a,(size_t)repeat.size);CHECK(vkResetCommandBuffer(cb,0));
            VkCommandBufferBeginInfo bi={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};CHECK(vkBeginCommandBuffer(cb,&bi));
            if(fmt==0x14&&layout==0) {
                vk_surf_use(cb,&s,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_PIPELINE_STAGE_2_COPY_BIT,VK_ACCESS_2_TRANSFER_WRITE_BIT);
                VkBufferImageCopy c[2]={
                    {.bufferRowLength=w,.imageSubresource={VK_IMAGE_ASPECT_DEPTH_BIT,0,0,1},.imageExtent={w,h,1}},
                    {.bufferOffset=plane,.bufferRowLength=sp,.imageSubresource={VK_IMAGE_ASPECT_STENCIL_BIT,0,0,1},.imageExtent={w,h,1}}};
                vkCmdCopyBufferToImage(cb,upload.b,s.img,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,2,c);
            }
            assert(snx_d24_pack_eligible(&s));assert(snx_d24_pack_pending(&s,s.gva,rt_bytes(&s)));
            assert(snx_d24_pack_record(cb,&s,out.b,32));
            u64 conversions=snx_d24_conversions;
            assert(snx_d24_pack_record(cb,&s,repeat.b,32));assert(snx_d24_conversions==conversions);
            int replace=w==20&&fmt==0x14&&layout==0;
            if(replace) {
                updated=buffer(upload.size);revised=buffer(out.size);memset(revised.p,0x5a,(size_t)revised.size);
                memcpy(updated.p,upload.p,(size_t)upload.size);
                for(u32 y=0;y<h;y++)for(u32 x=0;x<w;x++) {
                    u32 d=(((y*w+x)*337u)&0xffffff)^0x55aa55;
                    memcpy(updated.p+((u64)y*w+x)*4,&d,4);updated.p[plane+(u64)y*sp+x]^=0x3c;
                }
                vk_surf_use(cb,&s,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_PIPELINE_STAGE_2_COPY_BIT,VK_ACCESS_2_TRANSFER_WRITE_BIT);
                VkBufferImageCopy c[2]={
                    {.bufferRowLength=w,.imageSubresource={VK_IMAGE_ASPECT_DEPTH_BIT,0,0,1},.imageExtent={w,h,1}},
                    {.bufferOffset=plane,.bufferRowLength=sp,.imageSubresource={VK_IMAGE_ASPECT_STENCIL_BIT,0,0,1},.imageExtent={w,h,1}}};
                vkCmdCopyBufferToImage(cb,updated.b,s.img,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,2,c);
                s.wgen++;s.wseq+=100;
                assert(snx_d24_pack_record(cb,&s,revised.b,32));assert(snx_d24_conversions==conversions+1);
                // Restore the input for the other layout cases, still in this same command buffer.
                vk_surf_use(cb,&s,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_PIPELINE_STAGE_2_COPY_BIT,VK_ACCESS_2_TRANSFER_WRITE_BIT);
                vkCmdCopyBufferToImage(cb,upload.b,s.img,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,2,c);s.wgen++;s.wseq++;
            }
            VkMemoryBarrier2 host={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,.srcStageMask=VK_PIPELINE_STAGE_2_COPY_BIT,
                .srcAccessMask=VK_ACCESS_2_TRANSFER_WRITE_BIT,.dstStageMask=VK_PIPELINE_STAGE_2_HOST_BIT,.dstAccessMask=VK_ACCESS_2_HOST_READ_BIT};
            VkDependencyInfo hd={.sType=VK_STRUCTURE_TYPE_DEPENDENCY_INFO,.memoryBarrierCount=1,.pMemoryBarriers=&host};vkCmdPipelineBarrier2(cb,&hd);
            CHECK(vkEndCommandBuffer(cb));VkSubmitInfo si={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};
            CHECK(vkQueueSubmit(queue,1,&si,VK_NULL_HANDLE));CHECK(vkQueueWaitIdle(queue)); // test readback, not a runtime wait.
            u8* expected=malloc((size_t)out.size);assert(expected);memset(expected,0x5a,(size_t)out.size);
            for(u32 y=0;y<h;y++)for(u32 x=0;x<w;x++) {
                u32 d=((y*w+x)*337u)&0xffffff,st=(u8)(x*11+y*37),v;
                u64 at=s.bl?bl_offset(x*4,y,0,w*4,h,bl_height(h,s.bh),0):((u64)y*w+x)*4;
                v=fmt==0x14?(d<<8)|st:d|st<<24;memcpy(expected+32+at,&v,4);pixels+=2;
            }
            assert(!memcmp(out.p,expected,(size_t)out.size));assert(!memcmp(repeat.p,expected,(size_t)repeat.size));
            if(replace) {
                for(u32 y=0;y<h;y++)for(u32 x=0;x<w;x++) {
                    u32 d=(((y*w+x)*337u)&0xffffff)^0x55aa55,st=((u8)(x*11+y*37))^0x3c,v=(d<<8)|st;
                    memcpy(expected+32+((u64)y*w+x)*4,&v,4);pixels++;
                }
                assert(!memcmp(revised.p,expected,(size_t)revised.size));drop_buffer(updated);drop_buffer(revised);
            }
            free(expected);
        }
        vkDestroyImage(g_vk.dev,s.img,NULL);vkFreeMemory(g_vk.dev,im,NULL);drop_buffer(upload);drop_buffer(out);drop_buffer(repeat);
    }
    assert(snx_d24_reused>0&&snx_d24_conversions>0&&snx_d24_conversions<snx_d24_packed);
    printf("D24_REAL_VULKAN_OK pixels=%llu formats=2 layouts=linear,blocklinear block_heights=0,1,4 source_image_aspects=real production_recorder=1 all_guest_padding_preserved=1 private_workspace=1 cache_hits=%llu conversions=%llu\n",(unsigned long long)pixels,(unsigned long long)snx_d24_reused,(unsigned long long)snx_d24_conversions);
    vk_own_res_unref(snx_d24_work);snx_d24_work=NULL;vkDestroyPipeline(g_vk.dev,g_tc_pipe,NULL);vkDestroyPipelineLayout(g_vk.dev,g_tc_layout,NULL);
    vkDestroyDescriptorSetLayout(g_vk.dev,g_tc_ds,NULL);vkDestroyDescriptorPool(g_vk.dev,desc_pool,NULL);
    vkDestroyPipeline(g_vk.dev,g_bl_pipe,NULL);vkDestroyPipelineLayout(g_vk.dev,g_bl_layout,NULL);vkDestroyDescriptorSetLayout(g_vk.dev,g_bl_ds,NULL);
    vkDestroyCommandPool(g_vk.dev,pool,NULL);vkDestroyDevice(g_vk.dev,NULL);vkDestroyInstance(instance,NULL);free(texconv_spv);free(blocklinear_spv);
}
