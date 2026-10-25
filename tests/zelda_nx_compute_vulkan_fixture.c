/* Real Vulkan dispatch of the adapted synthetic tiled-light shader.
 * No game files, Android runtime or simulated GPU arithmetic. */
#include <vulkan/vulkan.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { VkResult r_=(x);if(r_!=VK_SUCCESS){fprintf(stderr,"Vulkan %d at %d\n",r_,__LINE__);exit(2);} } while(0)
typedef struct { VkBuffer buffer;VkDeviceMemory memory;uint32_t* data;VkDeviceSize bytes; } Buf;
static VkDevice dev;
static VkPhysicalDevice phys;
static Buf buffer(VkDeviceSize bytes,VkBufferUsageFlags usage) {
    Buf b={.bytes=bytes};
    VkBufferCreateInfo ci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=bytes,.usage=usage,
                          .sharingMode=VK_SHARING_MODE_EXCLUSIVE};
    CHECK(vkCreateBuffer(dev,&ci,NULL,&b.buffer));
    VkMemoryRequirements r;vkGetBufferMemoryRequirements(dev,b.buffer,&r);
    VkPhysicalDeviceMemoryProperties mp;vkGetPhysicalDeviceMemoryProperties(phys,&mp);
    uint32_t type=mp.memoryTypeCount;
    for(uint32_t i=0;i<mp.memoryTypeCount;i++)
        if((r.memoryTypeBits&(1u<<i)) && (mp.memoryTypes[i].propertyFlags&
           (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))==
           (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)){type=i;break;}
    assert(type<mp.memoryTypeCount);
    VkMemoryAllocateInfo ai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=r.size,.memoryTypeIndex=type};
    CHECK(vkAllocateMemory(dev,&ai,NULL,&b.memory));CHECK(vkBindBufferMemory(dev,b.buffer,b.memory,0));
    CHECK(vkMapMemory(dev,b.memory,0,VK_WHOLE_SIZE,0,(void**)&b.data));return b;
}
int main(int argc,char** argv) {
    assert(argc==2);
    FILE* f=fopen(argv[1],"rb");assert(f);assert(!fseek(f,0,SEEK_END));long n=ftell(f);assert(n>=20 && !(n&3));
    rewind(f);uint32_t* code=malloc((size_t)n);assert(code && fread(code,1,(size_t)n,f)==(size_t)n);assert(!fclose(f));
    VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,.pApplicationName="nxnative compute component",
                           .apiVersion=VK_API_VERSION_1_1};
    VkInstanceCreateInfo ii={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pApplicationInfo=&app};
    VkInstance instance;CHECK(vkCreateInstance(&ii,NULL,&instance));
    uint32_t count=0;CHECK(vkEnumeratePhysicalDevices(instance,&count,NULL));assert(count);
    VkPhysicalDevice* devices=calloc(count,sizeof *devices);assert(devices);
    CHECK(vkEnumeratePhysicalDevices(instance,&count,devices));phys=devices[0];free(devices);
    VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(phys,&props);
    vkGetPhysicalDeviceQueueFamilyProperties(phys,&count,NULL);
    VkQueueFamilyProperties* q=calloc(count,sizeof *q);assert(q);vkGetPhysicalDeviceQueueFamilyProperties(phys,&count,q);
    uint32_t family=count;
    for(uint32_t i=0;i<count;i++)if(q[i].queueFlags&VK_QUEUE_COMPUTE_BIT){family=i;break;}
    free(q);assert(family<count);
    float priority=1;
    VkDeviceQueueCreateInfo qi={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,.queueFamilyIndex=family,
                               .queueCount=1,.pQueuePriorities=&priority};
    VkDeviceCreateInfo di={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qi};
    CHECK(vkCreateDevice(phys,&di,NULL,&dev));VkQueue queue;vkGetDeviceQueue(dev,family,0,&queue);
    VkDescriptorSetLayoutBinding binding[5];
    const uint32_t slots[5]={0,4,18,19,20};
    for(int i=0;i<5;i++)binding[i]=(VkDescriptorSetLayoutBinding){.binding=slots[i],.descriptorCount=1,
        .descriptorType=i<2?VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER:VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
        .stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo li={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
                                       .bindingCount=5,.pBindings=binding};
    VkDescriptorSetLayout layout;CHECK(vkCreateDescriptorSetLayout(dev,&li,NULL,&layout));
    VkPipelineLayoutCreateInfo pi={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=1,.pSetLayouts=&layout};
    VkPipelineLayout pl;CHECK(vkCreatePipelineLayout(dev,&pi,NULL,&pl));
    VkShaderModuleCreateInfo mi={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=(size_t)n,.pCode=code};
    VkShaderModule module;CHECK(vkCreateShaderModule(dev,&mi,NULL,&module));free(code);
    VkComputePipelineCreateInfo ci={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.layout=pl,
        .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,
                .module=module,.pName="main"}};
    VkPipeline pipeline;CHECK(vkCreateComputePipelines(dev,VK_NULL_HANDLE,1,&ci,NULL,&pipeline));
    vkDestroyShaderModule(dev,module,NULL);
    VkDescriptorPoolSize sizes[2]={{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,2},{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,3}};
    VkDescriptorPoolCreateInfo dpi={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=1,
                                    .poolSizeCount=2,.pPoolSizes=sizes};
    VkDescriptorPool pool;CHECK(vkCreateDescriptorPool(dev,&dpi,NULL,&pool));
    VkDescriptorSetAllocateInfo dai={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=pool,
                                     .descriptorSetCount=1,.pSetLayouts=&layout};
    VkDescriptorSet set;CHECK(vkAllocateDescriptorSets(dev,&dai,&set));
    enum {N=1024};
    Buf b[5]={buffer(1024,VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT),buffer(16,VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT),
        buffer(N*4,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT),buffer(N*4,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT),
        buffer(N*4,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)};
    VkDescriptorBufferInfo bi[5];VkWriteDescriptorSet writes[5];
    for(int i=0;i<5;i++) {
        bi[i]=(VkDescriptorBufferInfo){b[i].buffer,0,b[i].bytes};
        writes[i]=(VkWriteDescriptorSet){.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=set,.dstBinding=slots[i],
            .descriptorCount=1,.descriptorType=binding[i].descriptorType,.pBufferInfo=&bi[i]};
    }
    vkUpdateDescriptorSets(dev,5,writes,0,NULL);
    VkCommandPoolCreateInfo cpi={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=family,
                                 .flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT};
    VkCommandPool cp;CHECK(vkCreateCommandPool(dev,&cpi,NULL,&cp));
    VkCommandBufferAllocateInfo cai={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=cp,
                                     .level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
    VkCommandBuffer cmd;CHECK(vkAllocateCommandBuffers(dev,&cai,&cmd));
    const uint32_t grids[][2]={{1,1},{20,17},{30,17},{5,4},{17,20},{32,32},{20,17}};
    unsigned checked=0;
    for(unsigned run=0;run<sizeof grids/sizeof grids[0];run++) {
        uint32_t w=grids[run][0],h=grids[run][1];
        memset(b[0].data,0,1024);memset(b[1].data,0,16);
        b[0].data[0x200/4]=w; /* genuine driver C0 layout; never a made-up replacement */
        b[1].data[0]=17+run;
        for(unsigned i=0;i<N;i++){b[2].data[i]=i*13+run;b[3].data[i]=b[4].data[i]=0xdeadbeef;}
        CHECK(vkResetCommandBuffer(cmd,0));
        VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};CHECK(vkBeginCommandBuffer(cmd,&begin));
        vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);
        vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pl,0,1,&set,0,NULL);
        vkCmdDispatch(cmd,w,h,1);
        VkMemoryBarrier barrier={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT,
                                  .dstAccessMask=VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,NULL,0,NULL);
        CHECK(vkEndCommandBuffer(cmd));
        VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cmd};
        CHECK(vkQueueSubmit(queue,1,&submit,VK_NULL_HANDLE));CHECK(vkQueueWaitIdle(queue));
        for(unsigned i=0;i<N;i++) {
            assert(b[3].data[i]==(i<w*h?i*13+run+17+run:0xdeadbeef));
            assert(b[4].data[i]==(i<w*h?i+1:0xdeadbeef));checked+=2;
        }
    }
    printf("VULKAN_NX_COMPUTE: %u values, 7 grids, exact tile lists/counts and untouched tails on %s\n",checked,props.deviceName);
    vkDestroyCommandPool(dev,cp,NULL);vkDestroyDescriptorPool(dev,pool,NULL);
    for(int i=0;i<5;i++){vkUnmapMemory(dev,b[i].memory);vkDestroyBuffer(dev,b[i].buffer,NULL);vkFreeMemory(dev,b[i].memory,NULL);}
    vkDestroyPipeline(dev,pipeline,NULL);vkDestroyPipelineLayout(dev,pl,NULL);vkDestroyDescriptorSetLayout(dev,layout,NULL);
    vkDestroyDevice(dev,NULL);vkDestroyInstance(instance,NULL);return 0;
}
