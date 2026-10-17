// Included by the real executor integration harness; all resources are synthetic.
static void test_program_free(Prog *p) {
    vkDestroyPipelineLayout(g_vk.dev, p->layout, NULL);
    for (unsigned i = 0; i < 2; ++i) {
        vkDestroyDescriptorSetLayout(g_vk.dev, p->set_layout[i], NULL);
        vkDestroyShaderModule(g_vk.dev, i ? p->fs : p->vs, NULL);
        free(p->spirv[i]);
    }
}
static void pipeline_replay_cases(bool warm) {
    vk_startup_replay_init();
    replay_wait_startup();
    char stats[512]; replay_stats(stats, sizeof stats); puts(stats);
    assert(strstr(stats, warm ? "loaded=3" : "loaded=0"));
    ShaderInfo vsi = {.msl =
        "#version 450\nlayout(location=0) in vec4 color; layout(location=0) out vec4 value;\n"
        "void main(){ vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));"
        "gl_Position=vec4(p[gl_VertexIndex],0,1); value=color; }\n"};
    ShaderInfo fsi = {.msl =
        "#version 450\nlayout(location=0) in vec4 value; layout(location=0) out vec4 color;\n"
        "layout(set=1,binding=0) uniform Tint{vec4 tint;}; void main(){color=value*tint;}\n"};
    Prog program = {.vi = &vsi, .fi = &fsi};
    run_job(compile_program, &program); build_ready(&program.state, "test program");
    Pipe graphics = {.k = {.prog = &program, .color = {VK_FORMAT_R8G8B8A8_UNORM}, .ncolor = 1, .samples = 1,
        .attr_fmt = {VK_FORMAT_R32G32B32A32_SFLOAT}, .attr_mask = 1, .used_streams = 1,
        .poly_fill = 1, .topo_class = 2, .write_mask = {15}}};
    int before = atomic_load(&stat_compiles);
    run_job(build_pipeline, &graphics); build_ready(&graphics.state, "test graphics pipeline");
    assert(atomic_load(&stat_compiles) == before + (warm ? 0 : 1));
    // A changed attachment write state must create a distinct pipeline.
    Pipe changed = {.k = graphics.k}; changed.k.write_mask[0] = 7;
    before = atomic_load(&stat_compiles);
    run_job(build_pipeline, &changed); build_ready(&changed.state, "test changed pipeline");
    assert(changed.pipe && changed.pipe != graphics.pipe);
    assert(atomic_load(&stat_compiles) == before + (warm ? 0 : 1));

    VkImageCreateInfo ii = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8G8B8A8_UNORM, .extent = {1,1,1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
    VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO};
    VkImage image; VmaAllocation image_mem; VK_CHECK(vmaCreateImage(g_vk.vma, &ii, &ai, &image, &image_mem, NULL));
    VkImageViewCreateInfo iv = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = image,
        .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = ii.format, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
    VkImageView view; VK_CHECK(vkCreateImageView(g_vk.dev, &iv, NULL, &view));
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = 4, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    VmaAllocationCreateInfo ri = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        .flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT};
    VkBuffer readback; VmaAllocation read_mem; VmaAllocationInfo info;
    VK_CHECK(vmaCreateBuffer(g_vk.vma, &bi, &ri, &readback, &read_mem, &info));
    float color[] = {1,0.5f,0.25f,1}, tint[] = {0.5f,1,0.5f,1};
    VkSpan vertices = vk_transient_copy(color, sizeof color, 16), uniform = vk_transient_copy(tint, sizeof tint, 256);
    VkDescriptorSet sets[2] = {vk_alloc_set(program.set_layout[0]), vk_alloc_set(program.set_layout[1])};
    VkDescriptorBufferInfo db = {uniform.buf, uniform.off, sizeof tint};
    VkWriteDescriptorSet write = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = sets[1], .dstBinding = 0,
        .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &db};
    vkUpdateDescriptorSets(g_vk.dev, 1, &write, 0, NULL);
    VkCommandBuffer cb = vk_cmd(); vk_image_init_layout(cb, image, VK_IMAGE_ASPECT_COLOR_BIT);
    VkRenderingAttachmentInfo attachment = {.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageView = view,
        .imageLayout = VK_IMAGE_LAYOUT_GENERAL, .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE};
    VkRenderingInfo render = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = {{0,0},{1,1}}, .layerCount = 1,
        .colorAttachmentCount = 1, .pColorAttachments = &attachment};
    vkCmdBeginRendering(cb, &render);
    dyn_defaults(cb);
    VkViewport vp = {0,0,1,1,0,1}; VkRect2D scissor = {{0,0},{1,1}};
    vkCmdSetViewport(cb, 0, 1, &vp); vkCmdSetScissor(cb, 0, 1, &scissor);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, graphics.pipe);
    // Sets/layout come from the live program; warm pipeline/layout were built
    // in a different process, from the persisted reflection dependencies.
    vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, program.layout, 0, 2, sets, 0, NULL);
    VkDeviceSize off = vertices.off; vkCmdBindVertexBuffers(cb, 0, 1, &vertices.buf, &off); vkCmdDraw(cb, 3, 1, 0, 0);
    vkCmdEndRendering(cb); vk_full_barrier(cb);
    VkBufferImageCopy copy = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT,0,0,1}, .imageExtent = {1,1,1}};
    vkCmdCopyImageToBuffer(cb, image, VK_IMAGE_LAYOUT_GENERAL, readback, 1, &copy);
    VkMemoryBarrier2 mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER_2, .srcStageMask = VK_PIPELINE_STAGE_2_TRANSFER_BIT,
        .srcAccessMask = VK_ACCESS_2_TRANSFER_WRITE_BIT, .dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT, .dstAccessMask = VK_ACCESS_2_HOST_READ_BIT};
    VkDependencyInfo dep = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .memoryBarrierCount = 1, .pMemoryBarriers = &mb};
    vkCmdPipelineBarrier2(cb, &dep); renderer_flush(); VK_CHECK(vmaInvalidateAllocation(g_vk.vma, read_mem, 0, 4));
    uint8_t *rgba = info.pMappedData;
    assert(abs((int)rgba[0]-128) <= 1 && abs((int)rgba[1]-128) <= 1 && abs((int)rgba[2]-32) <= 1 && rgba[3] == 255);

    ShaderInfo csi = {.msl = "#version 450\nlayout(local_size_x_id=0,local_size_y_id=1,local_size_z_id=2) in;\n"
        "layout(std430,set=0,binding=0) buffer Result{uint result;};"
        "void main(){if(gl_GlobalInvocationID.x==0) result=0xabc00000u+gl_WorkGroupSize.x;}\n"};
    CsProg compute = {.si = &csi, .local = {2,1,1}};
    before = atomic_load(&stat_compiles);
    run_job(build_compute, &compute); build_ready(&compute.p.state, "test compute pipeline");
    assert(atomic_load(&stat_compiles) == before + (warm ? 0 : 1));
    VkSpan output = vk_transient(16,256); memset(output.ptr,0,16);
    VkDescriptorSet set = vk_alloc_set(compute.p.set_layout[0]);
    db = (VkDescriptorBufferInfo){output.buf,output.off,16};
    write.dstSet = set; write.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    vkUpdateDescriptorSets(g_vk.dev, 1, &write, 0, NULL);
    cb = vk_cmd(); vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,compute.pipe);
    vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,compute.p.layout,0,1,&set,0,NULL);
    vkCmdDispatch(cb,1,1,1); gmem_host_barrier(cb); renderer_flush();
    for (int i = 0; i < nchunks; ++i) if (chunks[i].buf == output.buf)
        VK_CHECK(vmaInvalidateAllocation(g_vk.vma,chunks[i].mem,output.off,16));
    assert(*(uint32_t *)output.ptr == 0xabc00002u);
    replay_stop(); replay_stats(stats, sizeof stats); puts(stats);
    assert(strstr(stats, warm ? "rebuilt=3" : "registered=3"));
    assert(!warm || strstr(stats, "reused=3"));
    vk_spirv_cache_stats(stats, sizeof stats); puts(stats);
    bool corrupt_spirv = getenv("REPLAY_TEST_CORRUPT_SPIRV") != NULL;
    assert(strstr(stats, warm ? (corrupt_spirv ? "hits=2 compiled=1" : "hits=3 compiled=0") : "hits=0 compiled=3"));
    replay_destroy(); test_program_free(&program); test_program_free(&compute.p);
    vkDestroyImageView(g_vk.dev,view,NULL); vmaDestroyImage(g_vk.vma,image,image_mem);
    vmaDestroyBuffer(g_vk.vma,readback,read_mem);
    puts(warm ? "Startup replay: three retained pipelines reused, zero demand pipeline builds; correct tinted pixel and specialized compute result PASS"
              : "Startup replay: two graphics states + specialized compute recorded; correct tinted pixel and compute result PASS");
}
