/* SPDX-License-Identifier: MIT
 * End-to-end descriptor/support-buffer check on Vulkan (lavapipe in CI).
 * Draws two pixels through the actual ABI-2 adapted shader. No game data.
 */
#include <vulkan/vulkan.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
#define CHECK(call) do { VkResult r=(call); if(r!=VK_SUCCESS){fprintf(stderr,"%s: VkResult %d\n",#call,r);exit(1);} }while(0)
static VkDevice device;
static VkPhysicalDevice gpu;
static VkBuffer uniform_buffer;
static u8* uniform_data;
static u64 submission;
static unsigned validation_errors;
static VKAPI_ATTR VkBool32 VKAPI_CALL validation(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
    VkDebugUtilsMessageTypeFlagsEXT type,const VkDebugUtilsMessengerCallbackDataEXT* data,void* user) {
    (void)type;(void)user;
    if(severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT) {
        validation_errors++;fprintf(stderr,"VULKAN_VALIDATION_ERROR: %s\n",data->pMessage);
    }
    return VK_FALSE;
}
static u64 vk_submit_number(void){return submission;}
static u64 vk_stage_align(void){return 256;}
static u8* vk_stage(size_t n,u64 align,VkBuffer* b,u64* off){(void)align;assert(n<=4096);*b=uniform_buffer;*off=0;return uniform_data;}
#include "scarlet_support_v2.h"
static uint32_t memory_type(uint32_t bits,VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties p;vkGetPhysicalDeviceMemoryProperties(gpu,&p);
    for(u32 i=0;i<p.memoryTypeCount;i++)if((bits&(1u<<i))&&(p.memoryTypes[i].propertyFlags&flags)==flags)return i;
    fprintf(stderr,"required memory type missing\n");exit(1);
}
static VkDeviceMemory buffer(VkDeviceSize size,VkBufferUsageFlags usage,VkBuffer* b,void** mapped) {
    VkBufferCreateInfo ci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=size,.usage=usage};
    CHECK(vkCreateBuffer(device,&ci,NULL,b));VkMemoryRequirements req;vkGetBufferMemoryRequirements(device,*b,&req);
    VkMemoryAllocateInfo ai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,
        .memoryTypeIndex=memory_type(req.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    VkDeviceMemory m;CHECK(vkAllocateMemory(device,&ai,NULL,&m));CHECK(vkBindBufferMemory(device,*b,m,0));
    CHECK(vkMapMemory(device,m,0,VK_WHOLE_SIZE,0,mapped));return m;
}
static VkDeviceMemory image(int sampled,VkImage* image,VkImageView* view,void** mapped) {
    VkImageCreateInfo ci={.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,
        .format=VK_FORMAT_R8G8B8A8_UNORM,.extent={2,1,1},.mipLevels=1,.arrayLayers=1,.samples=VK_SAMPLE_COUNT_1_BIT,
        .tiling=sampled?VK_IMAGE_TILING_LINEAR:VK_IMAGE_TILING_OPTIMAL,
        .usage=sampled?VK_IMAGE_USAGE_SAMPLED_BIT:VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
        .initialLayout=sampled?VK_IMAGE_LAYOUT_PREINITIALIZED:VK_IMAGE_LAYOUT_UNDEFINED};
    CHECK(vkCreateImage(device,&ci,NULL,image));VkMemoryRequirements req;vkGetImageMemoryRequirements(device,*image,&req);
    VkMemoryAllocateInfo ai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,
        .memoryTypeIndex=memory_type(req.memoryTypeBits,sampled?VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT:0)};
    VkDeviceMemory m;CHECK(vkAllocateMemory(device,&ai,NULL,&m));CHECK(vkBindImageMemory(device,*image,m,0));
    if(sampled)CHECK(vkMapMemory(device,m,0,VK_WHOLE_SIZE,0,mapped));
    VkImageViewCreateInfo vi={.sType=VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=*image,.viewType=VK_IMAGE_VIEW_TYPE_2D,
        .format=ci.format,.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
    CHECK(vkCreateImageView(device,&vi,NULL,view));return m;
}
static VkShaderModule shader(const char* path) {
    FILE* f=fopen(path,"rb");assert(f);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);assert(n>0&&!(n&3));
    u32* data=malloc((size_t)n);assert(data);assert(fread(data,1,(size_t)n,f)==(size_t)n);fclose(f);
    VkShaderModuleCreateInfo ci={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=(size_t)n,.pCode=data};
    VkShaderModule s;CHECK(vkCreateShaderModule(device,&ci,NULL,&s));free(data);return s;
}
int main(int argc,char** argv) {
    assert(argc==3);
    const char* layers[]={"VK_LAYER_KHRONOS_validation"};const char* extensions[]={VK_EXT_DEBUG_UTILS_EXTENSION_NAME};
    VkDebugUtilsMessengerCreateInfoEXT debug={.sType=VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT,
        .messageSeverity=VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT,
        .messageType=VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT,
        .pfnUserCallback=validation};
    VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,.apiVersion=VK_API_VERSION_1_1};
    VkInstanceCreateInfo ici={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pNext=&debug,.pApplicationInfo=&app,
        .enabledLayerCount=1,.ppEnabledLayerNames=layers,.enabledExtensionCount=1,.ppEnabledExtensionNames=extensions};
    VkInstance instance;CHECK(vkCreateInstance(&ici,NULL,&instance));
    PFN_vkCreateDebugUtilsMessengerEXT create_debug=(PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance,"vkCreateDebugUtilsMessengerEXT");
    VkDebugUtilsMessengerEXT messenger;CHECK(create_debug(instance,&debug,NULL,&messenger));
    u32 ng=1;CHECK(vkEnumeratePhysicalDevices(instance,&ng,&gpu));assert(ng);
    VkPhysicalDeviceProperties properties;vkGetPhysicalDeviceProperties(gpu,&properties);printf("Vulkan device: %s\n",properties.deviceName);
    u32 nq=0;vkGetPhysicalDeviceQueueFamilyProperties(gpu,&nq,NULL);VkQueueFamilyProperties* qp=calloc(nq,sizeof *qp);vkGetPhysicalDeviceQueueFamilyProperties(gpu,&nq,qp);
    u32 family=0;while(family<nq&&!(qp[family].queueFlags&VK_QUEUE_GRAPHICS_BIT))family++;assert(family<nq);free(qp);
    float priority=1;VkDeviceQueueCreateInfo qi={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,.queueFamilyIndex=family,.queueCount=1,.pQueuePriorities=&priority};
    VkDeviceCreateInfo di={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qi};CHECK(vkCreateDevice(gpu,&di,NULL,&device));
    VkQueue queue;vkGetDeviceQueue(device,family,0,&queue);
    VkDeviceMemory um=buffer(4096,VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT,&uniform_buffer,(void**)&uniform_data);
    VkBuffer readback;u8* pixels;VkDeviceMemory rm=buffer(8,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&readback,(void**)&pixels);
    VkImage texture,target;VkImageView tv,ov;void* texture_data=NULL;
    VkDeviceMemory tm=image(1,&texture,&tv,&texture_data),om=image(0,&target,&ov,NULL);
    VkImageSubresource sub={VK_IMAGE_ASPECT_COLOR_BIT,0,0};VkSubresourceLayout sl;vkGetImageSubresourceLayout(device,texture,&sub,&sl);
    const u8 redgreen[8]={255,0,0,255,0,255,0,255};memcpy((u8*)texture_data+sl.offset,redgreen,8);
    VkSamplerCreateInfo sci={.sType=VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,.magFilter=VK_FILTER_NEAREST,.minFilter=VK_FILTER_NEAREST,
        .mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeV=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE};
    VkSampler sampler;CHECK(vkCreateSampler(device,&sci,NULL,&sampler));
    VkDescriptorSetLayoutBinding bindings[2]={{34,VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,1,VK_SHADER_STAGE_FRAGMENT_BIT,NULL},
        {106,VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1,VK_SHADER_STAGE_FRAGMENT_BIT,NULL}};
    VkDescriptorSetLayoutCreateInfo li={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};VkDescriptorSetLayout layouts[2];
    CHECK(vkCreateDescriptorSetLayout(device,&li,NULL,&layouts[0]));li.bindingCount=2;li.pBindings=bindings;CHECK(vkCreateDescriptorSetLayout(device,&li,NULL,&layouts[1]));
    VkPipelineLayoutCreateInfo pli={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=2,.pSetLayouts=layouts};
    VkPipelineLayout pl;CHECK(vkCreatePipelineLayout(device,&pli,NULL,&pl));
    VkDescriptorPoolSize sizes[2]={{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1},{VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,1}};
    VkDescriptorPoolCreateInfo dpi={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=1,.poolSizeCount=2,.pPoolSizes=sizes};VkDescriptorPool pool;CHECK(vkCreateDescriptorPool(device,&dpi,NULL,&pool));
    VkDescriptorSetAllocateInfo da={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=pool,.descriptorSetCount=1,.pSetLayouts=&layouts[1]};VkDescriptorSet set;CHECK(vkAllocateDescriptorSets(device,&da,&set));
    VkDescriptorBufferInfo bi={uniform_buffer,0,SNX_RYU_SUPPORT_SIZE};VkDescriptorImageInfo ii={sampler,tv,VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
    VkWriteDescriptorSet writes[2]={{.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=set,.dstBinding=34,.descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,.pImageInfo=&ii},
        {.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=set,.dstBinding=106,.descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,.pBufferInfo=&bi}};vkUpdateDescriptorSets(device,2,writes,0,NULL);
    VkAttachmentDescription attachment={.format=VK_FORMAT_R8G8B8A8_UNORM,.samples=VK_SAMPLE_COUNT_1_BIT,.loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR,
        .storeOp=VK_ATTACHMENT_STORE_OP_STORE,.initialLayout=VK_IMAGE_LAYOUT_UNDEFINED,.finalLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL};
    VkAttachmentReference color={0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};VkSubpassDescription sp={.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS,.colorAttachmentCount=1,.pColorAttachments=&color};
    VkSubpassDependency deps[2]={{VK_SUBPASS_EXTERNAL,0,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,0,VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,0},
        {0,VK_SUBPASS_EXTERNAL,VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,VK_ACCESS_TRANSFER_READ_BIT,0}};
    VkRenderPassCreateInfo rpci={.sType=VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,.attachmentCount=1,.pAttachments=&attachment,.subpassCount=1,.pSubpasses=&sp,.dependencyCount=2,.pDependencies=deps};
    VkRenderPass rp;CHECK(vkCreateRenderPass(device,&rpci,NULL,&rp));VkFramebufferCreateInfo fi={.sType=VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,.renderPass=rp,.attachmentCount=1,.pAttachments=&ov,.width=2,.height=1,.layers=1};VkFramebuffer fb;CHECK(vkCreateFramebuffer(device,&fi,NULL,&fb));
    VkShaderModule vs=shader(argv[1]),fs=shader(argv[2]);VkPipelineShaderStageCreateInfo stages[2]={{.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_VERTEX_BIT,.module=vs,.pName="main"},
        {.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_FRAGMENT_BIT,.module=fs,.pName="main"}};
    VkPipelineVertexInputStateCreateInfo vertex={.sType=VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};VkPipelineInputAssemblyStateCreateInfo ia={.sType=VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkViewport viewport={0,0,2,1,0,1};VkRect2D scissor={{0,0},{2,1}};VkPipelineViewportStateCreateInfo vp={.sType=VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,.viewportCount=1,.pViewports=&viewport,.scissorCount=1,.pScissors=&scissor};
    VkPipelineRasterizationStateCreateInfo raster={.sType=VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,.polygonMode=VK_POLYGON_MODE_FILL,.cullMode=VK_CULL_MODE_NONE,.frontFace=VK_FRONT_FACE_COUNTER_CLOCKWISE,.lineWidth=1};
    VkPipelineMultisampleStateCreateInfo ms={.sType=VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState ba={.colorWriteMask=15};VkPipelineColorBlendStateCreateInfo blend={.sType=VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,.attachmentCount=1,.pAttachments=&ba};
    VkGraphicsPipelineCreateInfo pci={.sType=VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,.stageCount=2,.pStages=stages,.pVertexInputState=&vertex,.pInputAssemblyState=&ia,.pViewportState=&vp,.pRasterizationState=&raster,.pMultisampleState=&ms,.pColorBlendState=&blend,.layout=pl,.renderPass=rp};
    VkPipeline pipeline;CHECK(vkCreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&pci,NULL,&pipeline));
    VkCommandPoolCreateInfo cpci={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,.queueFamilyIndex=family};VkCommandPool cp;CHECK(vkCreateCommandPool(device,&cpci,NULL,&cp));
    VkCommandBufferAllocateInfo cai={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=cp,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VkCommandBuffer cb;CHECK(vkAllocateCommandBuffers(device,&cai,&cb));
    for(unsigned test=0;test<2;test++) {
        float scales[65];for(int i=0;i<65;i++)scales[i]=1;scales[0]=(float)(test+1);submission++;
        VkBuffer used;u64 offset;assert(snx_ryu_support(scales,0,&used,&offset)&&used==uniform_buffer&&offset==0);
        CHECK(vkResetCommandBuffer(cb,0));VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};CHECK(vkBeginCommandBuffer(cb,&begin));
        if(!test) {
            VkImageMemoryBarrier barrier={.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT,.dstAccessMask=VK_ACCESS_SHADER_READ_BIT,
                .oldLayout=VK_IMAGE_LAYOUT_PREINITIALIZED,.newLayout=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
                .image=texture,.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
            vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_HOST_BIT,VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,0,0,NULL,0,NULL,1,&barrier);
        }
        VkMemoryBarrier host={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT,.dstAccessMask=VK_ACCESS_UNIFORM_READ_BIT};
        vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_HOST_BIT,VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,0,1,&host,0,NULL,0,NULL);
        VkClearValue clear={.color={{0,0,0,0}}};VkRenderPassBeginInfo rb={.sType=VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,.renderPass=rp,.framebuffer=fb,.renderArea={{0,0},{2,1}},.clearValueCount=1,.pClearValues=&clear};
        vkCmdBeginRenderPass(cb,&rb,VK_SUBPASS_CONTENTS_INLINE);vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_GRAPHICS,pl,1,1,&set,0,NULL);vkCmdDraw(cb,3,1,0,0);vkCmdEndRenderPass(cb);
        VkBufferImageCopy copy={.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={2,1,1}};vkCmdCopyImageToBuffer(cb,target,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,readback,1,&copy);
        VkMemoryBarrier read={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&read,0,NULL,0,NULL);CHECK(vkEndCommandBuffer(cb));
        VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};CHECK(vkQueueSubmit(queue,1,&submit,VK_NULL_HANDLE));CHECK(vkQueueWaitIdle(queue));
        u8 expected[8];memcpy(expected,redgreen,8);if(test)memcpy(expected+4,redgreen,4);
        if(memcmp(pixels,expected,8)){fprintf(stderr,"pixel test %u failed: %u,%u,%u,%u / %u,%u,%u,%u\n",test,pixels[0],pixels[1],pixels[2],pixels[3],pixels[4],pixels[5],pixels[6],pixels[7]);return 1;}
        printf("VULKAN_ABI2_PIXELS_OK: scale=%u, support UBO binding 106, texture binding 34\n",test+1);
    }
    vkDestroyCommandPool(device,cp,NULL);vkDestroyPipeline(device,pipeline,NULL);vkDestroyShaderModule(device,vs,NULL);vkDestroyShaderModule(device,fs,NULL);vkDestroyFramebuffer(device,fb,NULL);vkDestroyRenderPass(device,rp,NULL);vkDestroyDescriptorPool(device,pool,NULL);vkDestroyPipelineLayout(device,pl,NULL);vkDestroyDescriptorSetLayout(device,layouts[0],NULL);vkDestroyDescriptorSetLayout(device,layouts[1],NULL);vkDestroySampler(device,sampler,NULL);vkDestroyImageView(device,tv,NULL);vkDestroyImageView(device,ov,NULL);vkDestroyImage(device,texture,NULL);vkDestroyImage(device,target,NULL);vkUnmapMemory(device,tm);vkFreeMemory(device,tm,NULL);vkFreeMemory(device,om,NULL);vkDestroyBuffer(device,readback,NULL);vkUnmapMemory(device,rm);vkFreeMemory(device,rm,NULL);vkDestroyBuffer(device,uniform_buffer,NULL);vkUnmapMemory(device,um);vkFreeMemory(device,um,NULL);vkDestroyDevice(device,NULL);
    PFN_vkDestroyDebugUtilsMessengerEXT destroy_debug=(PFN_vkDestroyDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance,"vkDestroyDebugUtilsMessengerEXT");destroy_debug(instance,messenger,NULL);vkDestroyInstance(instance,NULL);
    assert(validation_errors==0);puts("VULKAN_ABI2_REGRESSIONS: 2 pixel checks passed; zero Vulkan validation errors");return 0;
}
