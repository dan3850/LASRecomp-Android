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
    uint64_t submitted = 0;
    if (test % 3) {
        renderer_submit();
        submitted = submit_seq;
        if (test % 3 == 2) {
            // Finish on the device without resolving the CPU copyback yet.
            VkSemaphoreWaitInfo wi = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO,
                .semaphoreCount = 1, .pSemaphores = &g_vk.timeline, .pValues = &submitted};
            VK_CHECK(vkWaitSemaphores(g_vk.dev, &wi, UINT64_MAX));
        }
        vk_cmd(); // later unrelated work must remain unsubmitted
    }
    gmem_read_range(HEAP_BASE + 0x20000,32);
    assert(!gmem_writes);
    if (submitted) {
        assert(submit_seq == submitted && subs[cur_sub].main_begun);
        renderer_flush();
    }
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
    uint64_t partial_before = stat_upload_bytes, saved_before = stat_gmem_reused_bytes;
    for (unsigned frame = 0; frame < 60; frame++) {
        guest[0x81234] = (uint8_t)(frame + 70);
        VkDescriptorBufferInfo partial = portable_gmem_map(0, false, tab);
        // All buffers are idle, so no replacement allocation is necessary.
        assert(partial.buffer == first.buffer || partial.buffer == changed.buffer);
        for (unsigned i = 0; i < GMEM_SNAP_SLOTS; i++) {
            struct GmemSnapshot *snap = &gmem_snap[i];
            if (snap->buf == partial.buffer) {
                assert(!memcmp(snap->shadow, guest + 0x80000, 1 << 20));
                // Test-only read: check bytes actually written to the mapping.
                assert(!memcmp(snap->mapped, guest + 0x80000, 1 << 20));
            }
        }
        vk_cmd(); renderer_flush();
    }
    assert(stat_upload_bytes - partial_before == 60ull * 4096);
    assert(stat_gmem_reused_bytes - saved_before == 60ull * ((1 << 20) - 4096));
    puts("GMEM partial updates: 60 changing 1 MiB snapshots copy 240 KiB; all output bytes preserved PASS");
    vk_cmd(); renderer_flush();
    gmem_snap_clear(); gmem_write_pool_clear();
    assert(!gmem_snap_bytes);
    memset(st.sbuf, 0, sizeof st.sbuf);
    puts("GMEM persistent snapshots: 61 submissions upload 1 MiB instead of 61 MiB; mutation/in-flight isolation/write isolation PASS");
}

// Exercise eviction against real mapped Vulkan allocations: the cache must
// borrow capacity from completed entries in other sets, never pending ones.
// Hash collisions must no longer force a transient upload when other
// snapshot slots are free. Keep six colliding 1 MiB buffers in one in-flight
// submission, then prove each immutable buffer can be found and reused.
static void snapshot_collision_spill(void) {
    assert(!gmem_snap_bytes);
    gmem_snap_enabled = 1;
    unsigned counts[GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS] = {0};
    const uint64_t heap = kernel_heap_size();
    const uint64_t limit = g_vk.props.limits.maxStorageBufferRange;
    for (unsigned off = 0; off <= (1 << 20); off += 4096) {
        GmemRange ranges[GMAP_MAX] = {{HEAP_BASE + off, 1 << 20}};
        GmemPlan p;
        assert(gmem_plan(&p, ranges, GMAP_MAX, HEAP_BASE, heap, limit));
        counts[hash_words(0, &p, sizeof p) % (GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS)]++;
    }
    unsigned group = 0;
    for (unsigned i = 0; i < GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS; ++i)
        if (counts[i] >= 6) { group = i; break; }
    assert(counts[group] >= 6);  // 257 candidates in only 32 groups
    VkBuffer retained[6] = {0};
    GmemPlan plans[6] = {0};
    unsigned found = 0;
    uint64_t uploaded = stat_upload_bytes;
    uint64_t bypassed = stat_gmem_busy_bypass;
    for (unsigned off = 0; off <= (1 << 20) && found < 6; off += 4096) {
        GmemRange ranges[GMAP_MAX] = {{HEAP_BASE + off, 1 << 20}};
        GmemPlan p;
        assert(gmem_plan(&p, ranges, GMAP_MAX, HEAP_BASE, heap, limit));
        if (hash_words(0, &p, sizeof p) % (GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS) != group) continue;
        VkSpan snap = gmem_read_snapshot(&p);
        assert(snap.buf);
        for (unsigned i = 0; i < found; ++i) assert(snap.buf != retained[i]);
        retained[found] = snap.buf;
        plans[found++] = p;
    }
    assert(found == 6 && gmem_snap_bytes == 6ull << 20);
    assert(stat_upload_bytes - uploaded == 6ull << 20);
    assert(stat_gmem_busy_bypass == bypassed);
    for (unsigned i = 0; i < found; ++i)
        assert(gmem_read_snapshot(&plans[i]).buf == retained[i]);
    vk_cmd(); renderer_flush();
    gmem_snap_clear();
    assert(!gmem_snap_bytes);
    puts("GMEM cache collisions: six pending snapshots share one old hash set without bypass or extra VRAM PASS");
}

static void snapshot_capacity_eviction(void) {
    assert(!gmem_snap_bytes);
    gmem_snap_enabled = 1;
    uint8_t *guest = (uint8_t *)(uintptr_t)HEAP_BASE;
    memset(guest, 0x6b, kernel_heap_size());
    GmemPlan saved[GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS] = {0};
    bool occupied[GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS] = {0};
    unsigned n = 0;
    // One completed 1 MiB snapshot per set, exactly filling the 32 MiB
    // budget. Vary addresses (not contents), finding distinct hash sets.
    for (unsigned off = 0; off <= (1 << 20) && n < GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS; off += 4096) {
        GmemRange range[GMAP_MAX] = {{HEAP_BASE + off, 1 << 20}};
        GmemPlan p;
        assert(gmem_plan(&p, range, GMAP_MAX, HEAP_BASE, kernel_heap_size(),
                         g_vk.props.limits.maxStorageBufferRange));
        assert(p.size == 1 << 20);
        unsigned set = hash_words(0, &p, sizeof p) % (GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS);
        if (occupied[set]) continue;
        VkSpan s = gmem_read_snapshot(&p);
        assert(s.buf);
        occupied[set] = true;
        saved[set] = p;
        n++;
        vk_cmd(); renderer_flush();
    }
    assert(n == GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS);
    vk_wait_seq(submit_seq);
    assert(gmem_snap_bytes == GMEM_SNAP_BUDGET);

    GmemRange range[GMAP_MAX] = {{HEAP_BASE, 2 << 20}};
    GmemPlan bigger;
    assert(gmem_plan(&bigger, range, GMAP_MAX, HEAP_BASE, kernel_heap_size(),
                     g_vk.props.limits.maxStorageBufferRange));
    assert(bigger.size == 2 << 20);
    unsigned target = hash_words(0, &bigger, sizeof bigger) % (GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS);

    // Mark all other sets as referenced by the still-recording submission.
    // Only the victim inside the target set is completed. It frees 1 MiB
    // but the 2 MiB request needs another 1 MiB from another set.
    for (unsigned set = 0; set < GMEM_SNAP_SLOTS / GMEM_SNAP_WAYS; ++set) {
        if (set == target) continue;
        VkSpan s = gmem_read_snapshot(&saved[set]);
        assert(s.buf);
    }
    uint64_t blocked_before = stat_gmem_budget_bypass;
    uint64_t evicted_before = stat_gmem_evictions;
    assert(!gmem_read_snapshot(&bigger).buf);
    assert(stat_gmem_budget_bypass == blocked_before + bigger.size);
    assert(stat_gmem_evictions == evicted_before);
    assert(gmem_snap_bytes == GMEM_SNAP_BUDGET);

    // Complete the protected submission. The same request must now succeed
    // by evicting one other completed entry, without increasing the budget.
    vk_cmd(); renderer_flush();
    vk_wait_seq(submit_seq);
    VkSpan s = gmem_read_snapshot(&bigger);
    assert(s.buf);
    assert(gmem_snap_bytes == GMEM_SNAP_BUDGET);
    assert(stat_gmem_evictions == evicted_before + 1);
    struct GmemSnapshot *chosen = NULL;
    for (unsigned i = 0; i < GMEM_SNAP_SLOTS; ++i)
        if (gmem_snap[i].buf == s.buf) chosen = &gmem_snap[i];
    assert(chosen && chosen->plan.size == bigger.size);
    assert(!memcmp(chosen->shadow, guest, (size_t)bigger.size));
    assert(!memcmp(chosen->mapped, guest, (size_t)bigger.size));
    vk_cmd(); renderer_flush();
    vk_wait_seq(submit_seq);
    gmem_snap_clear();
    assert(!gmem_snap_bytes);
    puts("GMEM cache capacity: pending buffers protected, completed cross-set LRU reclaimed within 32 MiB PASS");
}

// Persistent uniform staging: immutable repeated bindings, busy GPU fallback,
// and safe in-place refresh after timeline completion.
static void uniform_staging(void) {
    cbuf_snapshots_clear(); // isolate this case from earlier shader tests
    uint8_t *src = (uint8_t *)(uintptr_t)(HEAP_BASE + 0x90000);
    memset(src, 0x33, 8192);
    uint64_t before = stat_upload_bytes, saved = cbuf_saved_bytes;
    VkSpan first = guest_uniform_copy((uintptr_t)src, 8192);
    assert(first.buf && !first.ptr);
    assert(stat_upload_bytes - before == 8192);
    for (unsigned i = 0; i < 60; ++i) {
        VkSpan reused = guest_uniform_copy((uintptr_t)src, 4096);
        assert(reused.buf == first.buf);
    }
    assert(cbuf_saved_bytes - saved == 60ull * 4096);
    src[0] = 0x55;
    guest_copy_flush();
    VkSpan still_busy = guest_uniform_copy((uintptr_t)src, 8192);
    assert(still_busy.buf && still_busy.buf != first.buf);
    assert(still_busy.ptr && ((uint8_t *)still_busy.ptr)[0] == 0x55);
    for (unsigned i = 0; i < CBUF_SNAP_SLOTS; ++i) {
        CbufSnapshot *e = &cbuf_snap[i];
        if (e->buf == first.buf) {
            assert(e->shadow[0] == 0x33 && e->mapped[0] == 0x33);
        }
    }
    vk_cmd(); renderer_flush();
    uint64_t written = cbuf_written_bytes;
    VkSpan updated = guest_uniform_copy((uintptr_t)src, 8192);
    assert(updated.buf == first.buf);
    assert(cbuf_written_bytes - written == 256);
    unsigned found = 0;
    for (unsigned i = 0; i < CBUF_SNAP_SLOTS; ++i) {
        CbufSnapshot *e = &cbuf_snap[i];
        if (e->buf != first.buf) continue;
        assert(e->shadow[0] == 0x55 && e->mapped[0] == 0x55);
        found++;
    }
    assert(found == 1);
    vk_cmd(); renderer_flush();
    cbuf_snapshots_clear();
    assert(!cbuf_snap_bytes);
    puts("Uniform staging: 60 repeated bindings reused, pending GPU data immutable, completed copy refreshed 256 bytes PASS");
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
    assert(refreshed.buf == first.buf);
    unsigned found = 0;
    for (int i = 0; i < VTX_SNAPSHOT_SLOTS; i++) {
        VtxSnapshot *e = &vtx_snapshots[i];
        if (e->buf != first.buf) continue;
        assert(!memcmp(e->shadow, src, 8192));
        // Shadow is cached CPU memory; avoid reading write-combined mappings.
        found++;
    }
    assert(found == 1);
    VkSpan prefix = guest_vertex_copy((uintptr_t)src, 4096);
    assert(prefix.buf == refreshed.buf);
    vk_cmd(); renderer_flush();
    vtx_snapshots_clear();
    puts("Buffer reuse: 101 prefix requests copy 8192 bytes; invalidation, in-flight fallback and completed allocation reuse PASS");
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
        return 0;
    }
    // This portable test opts in; production desktop keeps the original default.
    setenv("LARECOMP_VK_CBUF_CACHE", "1", 1);
    init();
    for (unsigned i = 0; i < 13; ++i) run(argv[1],i);
    snapshots();
    split_counter_pairs();
    persistent_snapshots();
    snapshot_collision_spill();
    snapshot_capacity_eviction();
    buffer_reuse();
    uniform_staging();
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
