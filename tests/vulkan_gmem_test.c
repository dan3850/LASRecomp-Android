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
    VkPhysicalDeviceVulkan13Features f13 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES,
        .synchronization2 = true, .dynamicRendering = true};
    VkPhysicalDeviceVulkan12Features f12 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES,
        .pNext = &f13, .timelineSemaphore = true};
    VkPhysicalDeviceFeatures2 f = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &f12,
        .features = {.shaderInt64 = true}}; // deliberately no robustBufferAccess
    uint32_t nq = 16;
    VkQueueFamilyProperties qp[16];
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &nq, qp);
    VkQueueFlags want = VK_QUEUE_COMPUTE_BIT | VK_QUEUE_GRAPHICS_BIT;
    while (g_vk.qfam < nq && (qp[g_vk.qfam].queueFlags & want) != want) ++g_vk.qfam;
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

static void snapshots(void) {
    gmem_snap_enabled = 0; // baseline transient invalidation tests
    uint8_t *guest = (uint8_t *)(uintptr_t)HEAP_BASE;
    memset(st.sbuf, 0, sizeof st.sbuf);
    memset(st.ubuf, 0, sizeof st.ubuf);
    st.sbuf[0][0] = (Range){HEAP_BASE + 0x80000, 1 << 20};
    memset(guest + 0x80000, 0x31, 1 << 20);
    uint32_t tab[(GMAP_MAX + 1) * 4];
    uint64_t uploads = stat_upload_bytes;
    VkDescriptorBufferInfo first = portable_gmem_map(0, false, tab);
    for (int i = 0; i < 500; ++i) {
        VkDescriptorBufferInfo same = portable_gmem_map(0, false, tab);
        assert(same.buffer == first.buffer && same.offset == first.offset);
    }
    assert(stat_upload_bytes - uploads == 1 << 20);
    guest[0x80000] = 0x72;
    backend_pool_written(HEAP_BASE + 0x80000, 1);
    VkDescriptorBufferInfo changed = portable_gmem_map(0, false, tab);
    assert(changed.buffer != first.buffer || changed.offset != first.offset);
    guest[0x80000] = 0x19;
    guest_copy_flush(); // inline constant updates invalidate the snapshot too
    VkDescriptorBufferInfo inline_change = portable_gmem_map(0, false, tab);
    assert(inline_change.buffer != changed.buffer || inline_change.offset != changed.offset);
    uint8_t *first_ptr = NULL, *changed_ptr = NULL, *inline_ptr = NULL;
    for (int i = 0; i < nchunks; ++i) {
        if (chunks[i].buf == first.buffer) first_ptr = (uint8_t *)chunks[i].ptr + first.offset;
        if (chunks[i].buf == changed.buffer) changed_ptr = (uint8_t *)chunks[i].ptr + changed.offset;
        if (chunks[i].buf == inline_change.buffer) inline_ptr = (uint8_t *)chunks[i].ptr + inline_change.offset;
    }
    assert(first_ptr && changed_ptr && inline_ptr);
    assert(first_ptr[0] == 0x31 && changed_ptr[0] == 0x72 && inline_ptr[0] == 0x19);
    // A writable dispatch uses separate memory even when its bindings match.
    VkDescriptorBufferInfo writable = portable_gmem_map(0, true, tab);
    assert(writable.buffer != inline_change.buffer);
    uint64_t epoch = vk_cpu_write_generation(), gen = atomic_load(&gcopy_gen);
    vk_cmd(); renderer_flush();
    assert(!gmem_writes && gmem_free);
    // This dispatch did not write: do not dirty every atlas / snapshot.
    assert(vk_cpu_write_generation() == epoch && atomic_load(&gcopy_gen) == gen);
    VkDescriptorBufferInfo reused = portable_gmem_map(0, true, tab);
    assert(reused.buffer == writable.buffer);
    assert(gmem_writes->before[0] == 0x19 && gmem_writes->after[0] == 0x19);
    vk_cmd(); renderer_flush();
    uint64_t new_uploads = stat_upload_bytes;
    portable_gmem_map(0, false, tab); // new submission must take a fresh snapshot
    assert(stat_upload_bytes - new_uploads == 1 << 20);
    vk_cmd(); renderer_flush();
    gmem_write_pool_clear();
    assert(!gmem_free && !gmem_free_bytes && !gmem_free_count);
    memset(st.sbuf, 0, sizeof st.sbuf);
    puts("GMEM snapshots: 501 identical reads copy 1 MiB; CPU/inline/submission invalidation and safe compute reuse PASS");
}

static void split_counter_pairs(void) {
    uint64_t records[10][2] = {{0}};
    memset(&counter_pace_diag, 0, sizeof counter_pace_diag);
    counter_pace_diag.since_ns = plat_now_ns();
    counter_prev_out = 0;
    // Ten submissions wrap the eight-slot ring. Each pair is split between
    // submissions, matching the case the previous per-slot diagnostic lost.
    for (unsigned i = 0; i < 10; ++i) {
        VkCommandBuffer cb = vk_cmd();
        CounterQ *q = &cq[cur_sub];
        assert(q->pool && !q->n);
        vkCmdWriteTimestamp2(cb, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, q->pool, q->n);
        q->out[q->n++] = records[i];
        renderer_submit();
    }
    renderer_sync();
    assert(counter_pace_diag.reports == 10 && counter_pace_diag.pairs == 9);
    uint64_t pairs = counter_pace_diag.pairs;
    counter_pace_record(records[0], counter_prev_tick, g_vk.props.limits.timestampPeriod);
    assert(counter_pace_diag.pairs == pairs); // backwards/nonadjacent address
    counter_prev_out = 0;
    puts("GPU counter diagnostic: split submissions and ring wrap preserve adjacent intervals; nonadjacent records ignored PASS");
}

static void persistent_snapshots(void) {
    gmem_snap_enabled = 1;
    memset(st.sbuf, 0, sizeof st.sbuf);
    memset(st.ubuf, 0, sizeof st.ubuf);
    st.sbuf[0][0] = (Range){HEAP_BASE + 0x80000, 1 << 20};
    uint8_t *guest = (uint8_t *)(uintptr_t)HEAP_BASE;
    memset(guest + 0x80000, 0x23, 1 << 20);
    uint32_t tab[(GMAP_MAX + 1) * 4];
    gmem_snap_enabled = 0;
    uint64_t baseline = stat_upload_bytes;
    for (unsigned frame = 0; frame < 61; ++frame) {
        portable_gmem_map(0, false, tab);
        vk_cmd(); renderer_flush();
    }
    assert(stat_upload_bytes - baseline == 61ull << 20);
    gmem_snap_enabled = 1;
    uint64_t before = stat_upload_bytes;
    VkDescriptorBufferInfo first = portable_gmem_map(0, false, tab);
    for (unsigned frame = 0; frame < 60; ++frame) {
        vk_cmd(); renderer_flush();
        VkDescriptorBufferInfo same = portable_gmem_map(0, false, tab);
        assert(same.buffer == first.buffer && same.offset == first.offset);
    }
    assert(stat_upload_bytes - before == 1 << 20);
    // A changed byte, even without a CPU notification, must be observed by the
    // persistent cache in the next submission. Preserve the pending old copy.
    guest[0x81234] = 0x67;
    guest_copy_flush();
    VkDescriptorBufferInfo changed = portable_gmem_map(0, false, tab);
    assert(changed.buffer != first.buffer);
    struct GmemSnapshot *old = NULL, *fresh = NULL;
    for (unsigned i = 0; i < GMEM_SNAP_SLOTS; ++i) {
        if (gmem_snap[i].buf == first.buffer) old = &gmem_snap[i];
        if (gmem_snap[i].buf == changed.buffer) fresh = &gmem_snap[i];
    }
    assert(old && fresh && old->shadow[0x1234] == 0x23 && fresh->shadow[0x1234] == 0x67);
    VkDescriptorBufferInfo writable = portable_gmem_map(0, true, tab);
    assert(writable.buffer != changed.buffer && writable.buffer != first.buffer);
    vk_cmd(); renderer_flush();
    // Both allocations are now idle: refresh in place instead of reallocating.
    guest[0x81234] = 0x45;
    VkDescriptorBufferInfo updated = portable_gmem_map(0, false, tab);
    assert(updated.buffer == first.buffer || updated.buffer == changed.buffer);
    assert(gmem_snap_bytes == 2ull << 20);
    vk_cmd(); renderer_flush();
    gmem_snap_clear(); gmem_write_pool_clear();
    assert(!gmem_snap_bytes);
    memset(st.sbuf, 0, sizeof st.sbuf);
    puts("GMEM persistent snapshots: 61 submissions upload 1 MiB instead of 61 MiB; mutation/in-flight isolation/write isolation PASS");
}

static void buffer_reuse(void) {
    uint8_t *src = (uint8_t *)(uintptr_t)(HEAP_BASE + 0x80000);
    memset(src, 0x35, 8192);
    guest_copy_flush();
    uint64_t before = stat_upload_bytes;
    VkSpan large = guest_copy((uintptr_t)src, 8192);
    for (int i = 0; i < 100; i++) {
        VkSpan small = guest_copy((uintptr_t)src, 4096);
        assert(small.buf == large.buf && small.off == large.off);
    }
    assert(stat_upload_bytes - before == 8192);
    src[0] = 0x71;
    guest_copy_flush();
    VkSpan changed = guest_copy((uintptr_t)src, 4096);
    assert(changed.ptr != large.ptr && ((uint8_t *)large.ptr)[0] == 0x35);
    assert(((uint8_t *)changed.ptr)[0] == 0x71);

    setenv("LARECOMP_VK_STATIC_VTX_CACHE", "1", 1);
    VkSpan first = guest_vertex_copy((uintptr_t)src, 8192);
    assert(first.buf);
    src[0] = 0x19;
    // Still recording: changed bytes must use another buffer, without waiting.
    VkSpan inflight = guest_vertex_copy((uintptr_t)src, 8192);
    assert(inflight.buf != first.buf);
    vk_cmd(); renderer_flush();
    VkSpan refreshed = guest_vertex_copy((uintptr_t)src, 8192);
    assert(refreshed.buf == inflight.buf); // the already-copied version is still identical
    unsigned found = 0;
    for (int i = 0; i < VTX_SNAPSHOT_SLOTS; i++) {
        VtxSnapshot *e = &vtx_snapshots[i];
        if (e->buf != refreshed.buf) continue;
        assert(!memcmp(e->shadow, src, 8192));
        // Shadow is cached CPU memory; avoid reading write-combined mappings.
        found++;
    }
    assert(found == 1);
    VkSpan prefix = guest_vertex_copy((uintptr_t)src, 4096);
    assert(prefix.buf == refreshed.buf);
    vk_cmd(); renderer_flush();
    vtx_snapshots_clear();
    puts("Buffer reuse: 101 prefix requests copy 8192 bytes; invalidation, in-flight versions and prefix reuse PASS");
}

static VkShaderModule vertex_test_module(const char *dir, const char *name) {
    char path[1024]; snprintf(path, sizeof path, "%s/%s.spv", dir, name);
    FILE *f = fopen(path, "rb"); assert(f);
    fseek(f, 0, SEEK_END); long len = ftell(f); rewind(f);
    uint32_t *code = malloc(len); assert(code && fread(code, 1, len, f) == (size_t)len); fclose(f);
    VkShaderModuleCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = len, .pCode = code};
    VkShaderModule module; VK_CHECK(vkCreateShaderModule(g_vk.dev, &ci, NULL, &module)); free(code);
    return module;
}

static void vertex_pattern(uint8_t *src, unsigned version) {
    memset(src, 0x10 + version, 8192);
    const float color[] = {version * 0.25f, 0.25f, 0.5f, 1.0f};
    memcpy(src, color, sizeof color);
    guest_copy_flush(); // model an explicit guest update between recorded draws
}

static void vertex_versions(const char *dir) {
    uint8_t *src = (uint8_t *)(uintptr_t)(HEAP_BASE + 0x80000);
    VkShaderModule vs = vertex_test_module(dir, "snapshot.vert"), fs = vertex_test_module(dir, "snapshot.frag");
    VkPipelineLayoutCreateInfo li = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkPipelineLayout layout; VK_CHECK(vkCreatePipelineLayout(g_vk.dev, &li, NULL, &layout));
    VkPipelineShaderStageCreateInfo stages[] = {
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = vs, .pName = "main"},
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = fs, .pName = "main"}};
    VkVertexInputBindingDescription binding = {0, 0, VK_VERTEX_INPUT_RATE_VERTEX};
    VkVertexInputAttributeDescription attr = {0, 0, VK_FORMAT_R32G32B32A32_SFLOAT, 0};
    VkPipelineVertexInputStateCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
        .vertexBindingDescriptionCount = 1, .pVertexBindingDescriptions = &binding,
        .vertexAttributeDescriptionCount = 1, .pVertexAttributeDescriptions = &attr};
    VkPipelineInputAssemblyStateCreateInfo ia = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkPipelineViewportStateCreateInfo vp = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .scissorCount = 1};
    VkPipelineRasterizationStateCreateInfo rs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode = VK_POLYGON_MODE_FILL, .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState blend = {.colorWriteMask = 15};
    VkPipelineColorBlendStateCreateInfo bs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = 1, .pAttachments = &blend};
    VkDynamicState dyn[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo ds = {.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = 2, .pDynamicStates = dyn};
    VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;
    VkPipelineRenderingCreateInfo rendering = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO,
        .colorAttachmentCount = 1, .pColorAttachmentFormats = &format};
    VkGraphicsPipelineCreateInfo pi = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .pNext = &rendering,
        .stageCount = 2, .pStages = stages, .pVertexInputState = &vi, .pInputAssemblyState = &ia,
        .pViewportState = &vp, .pRasterizationState = &rs, .pMultisampleState = &ms,
        .pColorBlendState = &bs, .pDynamicState = &ds, .layout = layout};
    VkPipeline pipeline; VK_CHECK(vkCreateGraphicsPipelines(g_vk.dev, VK_NULL_HANDLE, 1, &pi, NULL, &pipeline));
    VkImageCreateInfo ii = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,
        .format = format, .extent = {5, 1, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
    VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO};
    VkImage image; VmaAllocation mem; VK_CHECK(vmaCreateImage(g_vk.vma, &ii, &ai, &image, &mem, NULL));
    VkImageViewCreateInfo iv = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = image,
        .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = format, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkImageView view; VK_CHECK(vkCreateImageView(g_vk.dev, &iv, NULL, &view));
    VkBufferCreateInfo rbi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = 20, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    VmaAllocationCreateInfo rai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        .flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT};
    VmaAllocationInfo rinfo; VmaAllocation rmem; VkSpan readback = {0};
    VK_CHECK(vmaCreateBuffer(g_vk.vma, &rbi, &rai, &readback.buf, &rmem, &rinfo));
    readback.ptr = rinfo.pMappedData;
    VkCommandBuffer cb = vk_cmd();
    vk_image_init_layout(cb, image, VK_IMAGE_ASPECT_COLOR_BIT);
    VkRenderingAttachmentInfo attachment = {.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,
        .imageView = view, .imageLayout = VK_IMAGE_LAYOUT_GENERAL, .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE};
    VkRenderingInfo ri = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = {{0,0},{5,1}},
        .layerCount = 1, .colorAttachmentCount = 1, .pColorAttachments = &attachment};
    vkCmdBeginRendering(cb, &ri);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);
    VkSpan versions[5];
    uint64_t before = stat_upload_bytes, waited = stat_wait_ns;
    for (unsigned i = 0; i < 5; ++i) {
        vertex_pattern(src, i);
        versions[i] = guest_vertex_copy((uintptr_t)src, 8192);
        VkDeviceSize off = versions[i].off;
        vkCmdBindVertexBuffers(cb, 0, 1, &versions[i].buf, &off);
        VkViewport viewport = {(float)i, 0, 1, 1, 0, 1};
        VkRect2D scissor = {{(int)i, 0}, {1, 1}};
        vkCmdSetViewport(cb, 0, 1, &viewport); vkCmdSetScissor(cb, 0, 1, &scissor);
        vkCmdDraw(cb, 3, 1, 0, 0);
        if (i < 4) for (unsigned j = 0; j < i; ++j) assert(versions[i].buf != versions[j].buf);
    }
    assert(vtx_snapshot_bytes == 4 * 8192 && vtx_snapshot_busy == 1);
    assert(stat_upload_bytes - before == 5 * 8192 && stat_wait_ns == waited);
    vkCmdEndRendering(cb); vk_full_barrier(cb);
    VkBufferImageCopy copy = {.bufferOffset = readback.off, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
        .imageExtent = {5,1,1}};
    vkCmdCopyImageToBuffer(cb, image, VK_IMAGE_LAYOUT_GENERAL, readback.buf, 1, &copy);
    VkMemoryBarrier2 mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2,
        .srcStageMask = VK_PIPELINE_STAGE_2_TRANSFER_BIT, .srcAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT,
        .dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT, .dstAccessMask = VK_ACCESS_2_HOST_READ_BIT};
    VkDependencyInfo dep = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .memoryBarrierCount = 1, .pMemoryBarriers = &mb};
    vkCmdPipelineBarrier2(cb, &dep);

    // Deterministically keep the real GPU reads pending behind a host-signalled
    // timeline gate. No sleep or GPU-speed assumption can make this test pass.
    VkSemaphoreTypeCreateInfo type = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO, .semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE};
    VkSemaphoreCreateInfo sci = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext = &type};
    VkSemaphore gate; VK_CHECK(vkCreateSemaphore(g_vk.dev, &sci, NULL, &gate));
    VkSemaphoreSubmitInfo wait = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, .semaphore = gate,
        .value = 1, .stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT};
    VkSubmitInfo2 submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO_2, .waitSemaphoreInfoCount = 1, .pWaitSemaphoreInfos = &wait};
    VK_CHECK(vkQueueSubmit2(g_vk.queue, 1, &submit, VK_NULL_HANDLE));
    renderer_submit();
    assert(vk_completed_seq() < submit_seq);
    before = stat_upload_bytes;
    for (unsigned repeat = 0; repeat < 32; ++repeat) {
        unsigned i = repeat % 4;
        vertex_pattern(src, i);
        assert(guest_vertex_copy((uintptr_t)src, 8192).buf == versions[i].buf);
    }
    assert(stat_upload_bytes == before); // versions survive across submissions
    vertex_pattern(src, 9);
    assert(guest_vertex_copy((uintptr_t)src, 8192).ptr); // all four readers are still pending
    for (unsigned i = 0; i < VTX_SNAPSHOT_SLOTS; ++i)
        if (vtx_snapshots[i].buf) assert(vtx_snapshots[i].shadow[8191] <= 0x13);
    vk_cmd(); renderer_submit();
    VkSemaphoreSignalInfo signal = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_SIGNAL_INFO, .semaphore = gate, .value = 1};
    VK_CHECK(vkSignalSemaphore(g_vk.dev, &signal));
    vk_wait_seq(submit_seq); VK_CHECK(vmaInvalidateAllocation(g_vk.vma, rmem, 0, 20));
    const uint8_t *pixels = readback.ptr;
    for (unsigned i = 0; i < 5; ++i) {
        assert(abs((int)pixels[i * 4] - (int)lroundf(i * 255.0f / 4)) <= 1);
        assert(abs((int)pixels[i * 4 + 1] - 64) <= 1 && abs((int)pixels[i * 4 + 2] - 128) <= 1 && pixels[i * 4 + 3] == 255);
    }
    uint64_t capacity = vtx_snapshot_bytes;
    VkSpan refreshed = guest_vertex_copy((uintptr_t)src, 8192);
    assert(!refreshed.ptr && vtx_snapshot_bytes == capacity); // completed buffer refreshed in place
    bool found = false;
    for (unsigned i = 0; i < 4; ++i) found |= refreshed.buf == versions[i].buf;
    assert(found);
    // Matching a prefix never validates a changed tail for a later larger draw.
    src[8191] ^= 1;
    assert(guest_vertex_copy((uintptr_t)src, 4096).buf == refreshed.buf);
    VkSpan tail = guest_vertex_copy((uintptr_t)src, 8192);
    assert(tail.buf != refreshed.buf);
    vk_cmd(); renderer_flush(); vtx_snapshots_clear();
    vkDestroySemaphore(g_vk.dev, gate, NULL); vkDestroyImageView(g_vk.dev, view, NULL); vmaDestroyImage(g_vk.vma, image, mem);
    vkDestroyPipeline(g_vk.dev, pipeline, NULL); vkDestroyPipelineLayout(g_vk.dev, layout, NULL);
    vkDestroyShaderModule(g_vk.dev, vs, NULL); vkDestroyShaderModule(g_vk.dev, fs, NULL);
    vmaDestroyBuffer(g_vk.vma, readback.buf, rmem);
    puts("Vertex snapshots: four pending versions + transient overflow render five correct colors; 32 cross-submission reuses upload zero bytes; completed refresh/prefix tail isolation PASS");
}

static void vertex_collisions_and_budget(void) {
    uint64_t addresses[4], count = 0, start = HEAP_BASE + 0x30000;
    for (uint64_t a = start; a < start + 0x50000 && count < 4; a += 16)
        if (vtx_snapshot_bucket(a) == vtx_snapshot_bucket(start)) addresses[count++] = a;
    assert(count == 4);
    VkBuffer buffers[4];
    for (unsigned i = 0; i < 4; ++i) {
        memset((void *)(uintptr_t)addresses[i], i + 1, 8192);
        buffers[i] = guest_vertex_copy(addresses[i], 8192).buf;
        for (unsigned j = 0; j < i; ++j) assert(buffers[i] != buffers[j]);
    }
    assert(vtx_snapshot_bytes == 4 * 8192 && !vtx_snapshot_busy);
    vk_cmd(); renderer_flush(); vtx_snapshots_clear();
    // Consume the entire byte budget in distinct buckets with synthetic data.
    bool used[VTX_SNAPSHOT_SLOTS] = {0};
    uint64_t last = 0;
    for (uint64_t a = start; a < start + 0x50000; a += 16) {
        unsigned bucket = vtx_snapshot_bucket(a);
        if (used[bucket]) continue;
        used[bucket] = true;
        VkSpan s = guest_vertex_copy(a, VTX_SNAPSHOT_MAX);
        if (vtx_snapshot_bytes == VTX_SNAPSHOT_BUDGET) { last = a; break; }
        assert(!s.ptr);
    }
    assert(last && vtx_snapshot_bytes == VTX_SNAPSHOT_BUDGET);
    // A different-size miss cannot exceed the budget or evict an in-flight way.
    VkSpan overflow = guest_vertex_copy(last + 16, VTX_SNAPSHOT_MAX - 16);
    assert(overflow.ptr && vtx_snapshot_bytes == VTX_SNAPSHOT_BUDGET);
    vk_cmd(); renderer_flush(); vtx_snapshots_clear();
    assert(!vtx_snapshot_bytes);
    puts("Vertex snapshots: colliding addresses isolated; 32 MiB byte budget and idle reset PASS");
}

static void write_pool_limits(void) {
    GmemWrite *w[10];
    for (unsigned i = 0; i < 10; ++i) w[i] = gmem_write_acquire(64);
    pthread_mutex_lock(&gmem_lock);
    for (unsigned i = 0; i < 10; ++i) gmem_write_recycle(w[i]);
    pthread_mutex_unlock(&gmem_lock);
    assert(gmem_free_count == 8 && gmem_free_bytes == 8 * 64);
    gmem_write_pool_clear();
    GmemWrite *large = gmem_write_acquire((16 << 20) + 64);
    pthread_mutex_lock(&gmem_lock); gmem_write_recycle(large); pthread_mutex_unlock(&gmem_lock);
    assert(!gmem_free && !gmem_free_bytes && !gmem_free_count);
    puts("GMEM compute pool: buffer-count and byte-capacity limits PASS");
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
        snprintf(path, sizeof path, "%s/snapshot.vert", argv[2]); f = fopen(path, "wb"); assert(f);
        fputs("#version 450\nlayout(location=0) in vec4 color; layout(location=0) out vec4 value;\n"
              "void main(){ vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));"
              "gl_Position=vec4(p[gl_VertexIndex],0,1); value=color; }\n", f); fclose(f);
        snprintf(path, sizeof path, "%s/snapshot.frag", argv[2]); f = fopen(path, "wb"); assert(f);
        fputs("#version 450\nlayout(location=0) in vec4 value; layout(location=0) out vec4 color;"
              "void main(){ color=value; }\n", f); fclose(f);
        return 0;
    }
    init();
    for (unsigned i = 0; i < 13; ++i) run(argv[1],i);
    snapshots();
    split_counter_pairs();
    persistent_snapshots();
    buffer_reuse();
    vertex_versions(argv[1]);
    vertex_collisions_and_budget();
    write_pool_limits();
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
