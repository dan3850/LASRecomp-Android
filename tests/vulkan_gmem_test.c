// Integration test: real executor allocations + real Maxwell LDG/STG, without
// game code, a window, or VK_EXT_external_memory_host. Unused executor sections
// are removed by --gc-sections. --emit DIR writes synthetic GLSL to compile.
#include <assert.h>
#include <sys/mman.h>
#include "../runtime/nvn/vulkan/exec.c"

VkG g_vk;
void rt_fatal_trace(void) { abort(); }
void vk_device_fault_report(void) { abort(); }
void vk_diag_info(const char *fmt, ...) { (void)fmt; }
void vk_diag_event(unsigned kind, const char *fmt, ...) { (void)kind; (void)fmt; }
uint64_t SDL_GetTicksNS(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec; }
uint64_t plat_now_ns(void) { return SDL_GetTicksNS(); }
int plat_written_pages(uint64_t a, uint64_t s, uint64_t *p, int n, uint64_t *pg) {
    (void)a; (void)s; (void)p; (void)n; *pg = 4096; return -1;
}
uint64_t vk_frame_counter(void) { return 1; } // deliberately never advance the atlas test's frame
uint64_t renderer_present_count(void) { return 1; }
uint32_t nvn_window_origin(void) { return 0; }
VkShaderModule vk_builtin_shader(const char *name) { (void)name; abort(); } // no presentation in this test
const float *vk_shot_crop(void) { abort(); }
void vk_save_png(const char *p, const uint8_t *d, uint32_t w, uint32_t h) {
    (void)p; (void)d; (void)w; (void)h; abort();
}
int texpatch_identify(const NvnTexture *t) { (void)t; return -1; }
uint32_t texpatch_generation(void) { return 0; }
void texpatch_apply(int i, uint32_t l, uint8_t *b, uint32_t w, uint32_t h, uint32_t r) {
    (void)i; (void)l; (void)b; (void)w; (void)h; (void)r;
}
uint64_t kernel_heap_size(void) { return 2 << 20; }

static uint64_t code[256];
static unsigned nc;
static void ins(uint64_t w) {
    if (!(nc % 4)) code[nc++] = 0x001f8000fc0007e0ull;
    code[nc++] = w;
}
static void mov(unsigned r, uint32_t v) { ins(0x010000000007f000ull | (uint64_t)v << 20 | r); }
static void addr(unsigned r, uint64_t a) { mov(r, (uint32_t)a); mov(r + 1, a >> 32); }
static void memop(bool store, unsigned size, unsigned r, unsigned a) {
    ins((store ? 0xeed8000000070000ull : 0xeed0000000070000ull) |
        1ull << 45 | (uint64_t)size << 48 | (uint64_t)a << 8 | r);
}
static const unsigned widths[] = {1,1,2,2,4,8,16};
static uint64_t source_addr(unsigned test) {
    if (test < 4) return HEAP_BASE + 0x10304 - widths[test]; // last byte/halfword of a mapped word
    if (test < 7) return HEAP_BASE + 0x10300;
    if (test == 7) return HEAP_BASE + 0x100000; // within heap, outside the descriptors
    if (test == 8) return HEAP_BASE + kernel_heap_size() - 4; // vector crosses the heap end
    if (test == 11) return HEAP_BASE + 0x40300; // LDG via a uniform-buffer GPU address
    return HEAP_BASE + 0x10300;
}
static char *shader(unsigned test) {
    nc = 0;
    memset(code, 0, sizeof code);
    addr(0, source_addr(test));
    addr(2, HEAP_BASE + 0x20000 + (test == 9 ? 3 : test == 10 ? 2 : 0));
    for (unsigned r = 8; r < 12; ++r) mov(r, 0);
    memop(false, test < 7 ? test : test == 9 || test == 10 ? 4 : 6, 8, 0);
    memop(true, test == 9 ? 0 : test == 10 ? 2 : 6, 8, 2);
    // This unmapped store must leave both the dummy buffer and guest heap intact.
    addr(4, HEAP_BASE + 0x80000);
    memop(true, 4, 8, 4);
    ins(0xe30000000007000full);
    ins(0xe2400fffff87000full);
    maxwell_gmem_base = HEAP_BASE;
    maxwell_gmem_size = kernel_heap_size();
    ShaderKey key = {.glsl = 1};
    ShaderInfo *si = maxwell_translate((const uint8_t *)code, nc * 8, STAGE_COMPUTE, &key);
    if (!si->msl) { fprintf(stderr, "%s\n", si->error); abort(); }
    assert(si->uses_gmem_map && si->uses_gmem_store);
    char *out = strdup(si->msl);
    maxwell_free(si);
    return out;
}

static void init(void) {
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_3};
    VkInstanceCreateInfo ii = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
    VK_CHECK(vkCreateInstance(&ii, NULL, &g_vk.inst));
    uint32_t count = 1;
    VK_CHECK(vkEnumeratePhysicalDevices(g_vk.inst, &count, &g_vk.phys));
    vkGetPhysicalDeviceProperties(g_vk.phys, &g_vk.props);
    printf("Vulkan device: %s; host import disabled\n", g_vk.props.deviceName);
    VkPhysicalDeviceVulkan13Features f13 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES, .synchronization2 = true};
    VkPhysicalDeviceVulkan12Features f12 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES,
        .pNext = &f13, .timelineSemaphore = true};
    VkPhysicalDeviceFeatures2 f = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &f12,
        .features = {.shaderInt64 = true}}; // deliberately no robustBufferAccess
    uint32_t nq = 16;
    VkQueueFamilyProperties qp[16];
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &nq, qp);
    while (g_vk.qfam < nq && !(qp[g_vk.qfam].queueFlags & VK_QUEUE_COMPUTE_BIT)) ++g_vk.qfam;
    assert(g_vk.qfam < nq);
    float prio = 1;
    VkDeviceQueueCreateInfo qi = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = g_vk.qfam, .queueCount = 1, .pQueuePriorities = &prio};
    VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &f,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi};
    VK_CHECK(vkCreateDevice(g_vk.phys, &di, NULL, &g_vk.dev));
    vkGetDeviceQueue(g_vk.dev, g_vk.qfam, 0, &g_vk.queue);
    VmaAllocatorCreateInfo ai = {.instance = g_vk.inst, .physicalDevice = g_vk.phys,
        .device = g_vk.dev, .vulkanApiVersion = VK_API_VERSION_1_3};
    VK_CHECK(vmaCreateAllocator(&ai, &g_vk.vma));
    VkSemaphoreTypeCreateInfo ti = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO,
        .semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE};
    VkSemaphoreCreateInfo si = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext = &ti};
    VK_CHECK(vkCreateSemaphore(g_vk.dev, &si, NULL, &g_vk.timeline));
    VkCommandPoolCreateInfo pi = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = g_vk.qfam};
    VK_CHECK(vkCreateCommandPool(g_vk.dev, &pi, NULL, &g_vk.pool));
    void *guest = mmap((void *)(uintptr_t)HEAP_BASE, kernel_heap_size(), PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    assert(guest == (void *)(uintptr_t)HEAP_BASE);
}

static void run(const char *dir, unsigned test) {
    uint8_t *guest = (uint8_t *)(uintptr_t)HEAP_BASE;
    memset(guest, 0xa5, kernel_heap_size());
    static const uint8_t input[16] = {0x81,0x7f,0x92,0xe3,0x55,0x66,0x77,0x88,1,2,3,4,5,6,7,8};
    memcpy(guest + 0x10300, input, 16);
    memcpy(guest + 0x40300, input, 16);
    memset(st.sbuf, 0, sizeof st.sbuf);
    memset(st.ubuf, 0, sizeof st.ubuf);
    st.sbuf[5][0] = (Range){HEAP_BASE + 0x10300, test < 4 ? 4 : 16};
    st.sbuf[5][1] = (Range){HEAP_BASE + 0x20000, 32};
    // Alias: the planner must merge this, not return the shorter matching range.
    st.sbuf[5][2] = (Range){HEAP_BASE + 0x10300, 2};
    if (test == 11) st.ubuf[5][0] = (Range){HEAP_BASE + 0x40300, 16};
    uint32_t tab[(GMAP_MAX + 1) * 4];
    VkDescriptorBufferInfo packed = portable_gmem_map(5, true, tab);
    assert(gmem_overlaps(HEAP_BASE + 0x20000, 1));
    assert(!gmem_overlaps(HEAP_BASE + 0x20020, 1));
    if (test == 12) {
        uint32_t unused[(GMAP_MAX + 1) * 4];
        memset(guest + 0x10300, 0xcc, 16);
        VkDescriptorBufferInfo other = portable_gmem_map(5, true, unused);
        assert(other.buffer != packed.buffer); // another dispatch cannot clobber this dispatch's inputs
    }
    gmem_resolve_done(submit_seq); // unsubmitted output must not be applied
    assert(gmem_writes && guest[0x20000] == 0xa5);
    // A neighbouring byte changed by the CPU is not overwritten by readback.
    guest[0x2001f] = 0x42;
    uint32_t zero[1024] = {0};
    VkSpan zs = vk_transient_copy(zero, sizeof zero, 256);
    VkSpan ts = vk_transient_copy(tab, sizeof tab, 256);
    VkDescriptorBufferInfo db[3] = {{zs.buf,zs.off,sizeof zero}, {ts.buf,ts.off,sizeof tab}, packed};
    VkDescriptorSetLayoutBinding bindings[3] = {
        {17,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL},
        {20,VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL},
        {21,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL}};
    VkDescriptorSetLayoutCreateInfo li = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .bindingCount = 3, .pBindings = bindings};
    VkDescriptorSetLayout layout;
    VK_CHECK(vkCreateDescriptorSetLayout(g_vk.dev, &li, NULL, &layout));
    VkPipelineLayoutCreateInfo pli = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &layout};
    VkPipelineLayout pl;
    VK_CHECK(vkCreatePipelineLayout(g_vk.dev, &pli, NULL, &pl));
    VkDescriptorPoolSize sizes[] = {{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,2},{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1}};
    VkDescriptorPoolCreateInfo dpi = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1,
        .poolSizeCount = 2, .pPoolSizes = sizes};
    VkDescriptorPool pool;
    VK_CHECK(vkCreateDescriptorPool(g_vk.dev, &dpi, NULL, &pool));
    VkDescriptorSetAllocateInfo dai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool = pool, .descriptorSetCount = 1, .pSetLayouts = &layout};
    VkDescriptorSet ds;
    VK_CHECK(vkAllocateDescriptorSets(g_vk.dev, &dai, &ds));
    VkWriteDescriptorSet writes[3];
    for (unsigned i = 0; i < 3; ++i) writes[i] = (VkWriteDescriptorSet){.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
        .dstSet = ds, .dstBinding = bindings[i].binding, .descriptorCount = 1, .descriptorType = bindings[i].descriptorType, .pBufferInfo = &db[i]};
    vkUpdateDescriptorSets(g_vk.dev, 3, writes, 0, NULL);
    char path[1024];
    snprintf(path, sizeof path, "%s/gmem%u.spv", dir, test);
    FILE *f = fopen(path, "rb"); assert(f);
    fseek(f, 0, SEEK_END); long len = ftell(f); rewind(f);
    uint32_t *spv = malloc(len); assert(fread(spv,1,len,f) == (size_t)len); fclose(f);
    VkShaderModuleCreateInfo mi = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = len, .pCode = spv};
    VkShaderModule mod;
    VK_CHECK(vkCreateShaderModule(g_vk.dev, &mi, NULL, &mod)); free(spv);
    uint32_t locals[3] = {1,1,1};
    VkSpecializationMapEntry entries[] = {{0,0,4},{1,4,4},{2,8,4}};
    VkSpecializationInfo spec = {.mapEntryCount = 3,.pMapEntries = entries,.dataSize = sizeof locals,.pData = locals};
    VkComputePipelineCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = pl,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                  .module = mod, .pName = "main", .pSpecializationInfo = &spec}};
    VkPipeline pipe;
    VK_CHECK(vkCreateComputePipelines(g_vk.dev, VK_NULL_HANDLE, 1, &ci, NULL, &pipe));
    VkCommandBuffer cb = vk_cmd();
    vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipe);
    vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pl,0,1,&ds,0,NULL);
    vkCmdDispatch(cb,1,1,1);
    gmem_host_barrier(cb);
    // Exercise the actual dependency path: submit, timeline wait, invalidate,
    // copyback, then allow the CPU snapshot. No manual completion shortcut.
    gmem_read_range(HEAP_BASE + 0x20000,32);
    assert(!gmem_writes);
    uint32_t expected[4] = {0};
    if (test < 7) {
        unsigned off = source_addr(test) - HEAP_BASE - 0x10300;
        memcpy(expected,input+off,widths[test]);
        if (test == 1) expected[0] = (uint32_t)(int32_t)(int8_t)expected[0];
        if (test == 3) expected[0] = (uint32_t)(int32_t)(int16_t)expected[0];
    }
    if (test == 9 || test == 10) {
        memset(expected,0xa5,sizeof expected);
        memcpy((uint8_t *)expected + (test == 9 ? 3 : 2),input,test == 9 ? 1 : 2);
    }
    if (test == 11 || test == 12) memcpy(expected,input,16);
    if (memcmp(guest+0x20000,expected,16)) {
        fprintf(stderr,"test %u: got %08x expected %08x\n",test,*(uint32_t *)(guest+0x20000),expected[0]); abort();
    }
    assert(guest[0x2001f] == 0x42 && guest[0x80000] == 0xa5);
    for (unsigned i = 0; i < sizeof zero; ++i) assert(((uint8_t *)zs.ptr)[i] == 0);
    vkDestroyPipeline(g_vk.dev,pipe,NULL); vkDestroyShaderModule(g_vk.dev,mod,NULL);
    vkDestroyDescriptorPool(g_vk.dev,pool,NULL); vkDestroyPipelineLayout(g_vk.dev,pl,NULL);
    vkDestroyDescriptorSetLayout(g_vk.dev,layout,NULL);
    printf("GMEM case %u: LDG/STG and deferred selective writeback PASS\n",test);
}

static void atlas(const char *dir) {
    uint8_t *pixels = (uint8_t *)(uintptr_t)(HEAP_BASE + 0x30000);
    memset(pixels, 0, 512);
    NvnTexture t = {.addr = (uintptr_t)pixels, .width = 64, .height = 8, .depth = 1,
        .target = 1, .format = 1, .flags = 0x10, .stride = 64, .levels = 1, .samples = 1,
        .swizzle = {1,1,1,2}};
    t.layout = (TexLayout){.width = 64,.height = 8,.depth = 1,.layers = 1,.levels = 1,.fmt = nvn_format_info(1)};
    tegra_layout_init(&t.layout);
    NvnTexEntry entry[2] = {{0}, {.tex = &t}};
    NvnDescPool tp = {.count = 2,.entries = entry};
    NvnSamplerDesc sampler = {.min_filter = 1,.mag_filter = 1,.lod_max = 1000};
    NvnDescPool sp = {.count = 1,.entries = &sampler};
    st.spool = &sp;
    st.tpool = &tp; st.tex[1][0] = 1;
    ShaderInfo si = {.ntex = 1,.tex = {{.handle_offset = 0x20,.type = TEXTYPE_2D}}};
    char path[1024]; snprintf(path,sizeof path,"%s/atlas.spv",dir);
    FILE *f = fopen(path,"rb"); assert(f); fseek(f,0,SEEK_END); long len = ftell(f); rewind(f);
    uint32_t *spv = malloc(len); assert(fread(spv,1,len,f) == (size_t)len); fclose(f);
    VkShaderModuleCreateInfo mi = {.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=len,.pCode=spv};
    VkShaderModule mod; VK_CHECK(vkCreateShaderModule(g_vk.dev,&mi,NULL,&mod)); free(spv);
    VkDescriptorSetLayoutBinding bindings[] = {
        {0,VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL},
        {1,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL}};
    VkDescriptorSetLayoutCreateInfo li = {.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=2,.pBindings=bindings};
    VkDescriptorSetLayout layout; VK_CHECK(vkCreateDescriptorSetLayout(g_vk.dev,&li,NULL,&layout));
    VkPipelineLayoutCreateInfo pli = {.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=1,.pSetLayouts=&layout};
    VkPipelineLayout pl; VK_CHECK(vkCreatePipelineLayout(g_vk.dev,&pli,NULL,&pl));
    VkComputePipelineCreateInfo ci = {.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.layout=pl,
        .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=mod,.pName="main"}};
    VkPipeline pipe; VK_CHECK(vkCreateComputePipelines(g_vk.dev,VK_NULL_HANDLE,1,&ci,NULL,&pipe));
    for (int update = 0; update < 2; ++update) {
        if (update) { pixels[0] = 128; backend_pool_written((uintptr_t)pixels,1); }
        VkDescriptorImageInfo image;
        float scale[2]; uint32_t wh[2];
        // Exercises the real per-frame view memo, R8 upload, swizzle and sampler.
        texture_info(1,&si,0,&image,scale,wh);
        VkSpan output = vk_transient(16,256);
        memset(output.ptr,0xcc,16);
        VkDescriptorBufferInfo data = {output.buf,output.off,16};
        VkDescriptorSet ds = vk_alloc_set(layout);
        VkWriteDescriptorSet writes[] = {
            {.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=ds,.dstBinding=0,.descriptorCount=1,
             .descriptorType=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,.pImageInfo=&image},
            {.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=ds,.dstBinding=1,.descriptorCount=1,
             .descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.pBufferInfo=&data}};
        vkUpdateDescriptorSets(g_vk.dev,2,writes,0,NULL);
        VkCommandBuffer cb = vk_cmd();
        vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipe);
        vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pl,0,1,&ds,0,NULL);
        vkCmdDispatch(cb,1,1,1); gmem_host_barrier(cb);
        renderer_flush();
        for (int i = 0; i < nchunks; ++i) if (chunks[i].buf == output.buf)
            VK_CHECK(vmaInvalidateAllocation(g_vk.vma,chunks[i].mem,output.off,16));
        const float *rgba = output.ptr;
        assert(rgba[0] == 1 && rgba[1] == 1 && rgba[2] == 1);
        assert(fabsf(rgba[3] - (update ? 128.0f/255.0f : 0.0f)) < 0.001f);
    }
    puts("R8 atlas: upload -> view memo -> white RGB/red alpha -> sampler; same-frame glyph update PASS");
    renderer_flush();
    backend_texture_destroyed(&t);
    vk_cmd(); renderer_flush(); // retire deferred image/view destruction
    vk_collect_dead();
    vkDestroyPipeline(g_vk.dev,pipe,NULL); vkDestroyShaderModule(g_vk.dev,mod,NULL);
    vkDestroyPipelineLayout(g_vk.dev,pl,NULL); vkDestroyDescriptorSetLayout(g_vk.dev,layout,NULL);
    vkDestroySampler(g_vk.dev,(VkSampler)sampler.backend,NULL);
}

int main(int argc, char **argv) {
    setvbuf(stdout,NULL,_IONBF,0);
    assert(argc == 2 || argc == 3);
    if (argc == 3 && !strcmp(argv[1],"--emit")) {
        for (unsigned i = 0; i < 13; ++i) {
            char path[1024]; snprintf(path,sizeof path,"%s/gmem%u.comp",argv[2],i);
            FILE *f = fopen(path,"wb"); assert(f);
            char *s = shader(i); fputs(s,f); free(s); fclose(f);
        }
        char path[1024]; snprintf(path,sizeof path,"%s/atlas.comp",argv[2]);
        FILE *f = fopen(path,"wb"); assert(f);
        fputs("#version 450\nlayout(local_size_x=1) in;\nlayout(binding=0) uniform sampler2D atlas_;\n"
              "layout(std430,binding=1) buffer Output { vec4 rgba; };\n"
              "void main() { rgba = textureLod(atlas_,vec2(0.5/64.0,0.5/8.0),0.0); }\n",f);
        fclose(f);
        return 0;
    }
    init();
    for (unsigned i = 0; i < 13; ++i) run(argv[1],i);
    atlas(argv[1]);
    vkDeviceWaitIdle(g_vk.dev);
    for (int i = 0; i < nchunks; ++i) vmaDestroyBuffer(g_vk.vma,chunks[i].buf,chunks[i].mem);
    free(chunks);
    munmap((void *)(uintptr_t)HEAP_BASE,kernel_heap_size());
    for (int i = 0; i < SUBS; ++i) {
        for (int j = 0; j < subs[i].npools; ++j) vkDestroyDescriptorPool(g_vk.dev,subs[i].pools[j],NULL);
        if (cq[i].pool) vkDestroyQueryPool(g_vk.dev,cq[i].pool,NULL);
    }
    vkDestroyCommandPool(g_vk.dev,g_vk.pool,NULL); vkDestroySemaphore(g_vk.dev,g_vk.timeline,NULL);
    vmaDestroyAllocator(g_vk.vma); vkDestroyDevice(g_vk.dev,NULL); vkDestroyInstance(g_vk.inst,NULL);
}
