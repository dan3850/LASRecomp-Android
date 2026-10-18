// Prepares content-addressed Maxwell programs and real Vulkan pipelines from the
// player's own BNSH archives. NVN draw/dispatch paths still use replay_get.
// The original record discovery format is MIT-licensed LASRecomp PR #91.
// Called only after the Vulkan device and replay registry exist.
static unsigned las_headstart_ready, las_headstart_failed;

bool renderer_prepare_begin(void) {
    return g_vk.dev != VK_NULL_HANDLE && g_vk.pcache != VK_NULL_HANDLE;
}

int renderer_prepare_pending(void) { return 0; }

void renderer_prepare_end(void) {
    vk_pipeline_cache_save();
    LOG("[shader-headstart] Vulkan pipelines ready=%u failed=%u\n",
        las_headstart_ready, las_headstart_failed);
}

static bool headstart_translate(const ShaderBlob *blob, int stage,
                                const ShaderKey *key, ShaderInfo **info,
                                uint32_t **spirv, size_t *words) {
    if (!blob || !blob->code || !blob->const_offset || blob->const_offset > blob->size)
        return false;
    pthread_mutex_lock(&translate_lock);
    maxwell_gmem_base = HEAP_BASE;
    maxwell_gmem_size = HEAP_MAX;
    *info = maxwell_translate(blob->code, blob->const_offset, stage, key);
    pthread_mutex_unlock(&translate_lock);
    if (!*info || !(*info)->msl) return false;
    *spirv = vk_glsl_to_spirv((*info)->msl, stage, "headstart", words);
    return *spirv != NULL;
}

bool renderer_prepare(const ShaderRec *r, const ShaderBlob *vsb, const ShaderBlob *fsb) {
    if (!r || (r->kind != 'G' && r->kind != 'C')) return false;
    ShaderInfo *vi = NULL, *fi = NULL;
    uint32_t *sv = NULL, *sf = NULL;
    size_t nv = 0, nf = 0;
    bool good = false;
    ShaderKey vk = {0}, fk = {0};
    vk.glsl = fk.glsl = 1;

    if (r->kind == 'C') {
        if (r->local[0] && r->local[1] && r->local[2] &&
            headstart_translate(vsb, STAGE_COMPUTE, &vk, &vi, &sv, &nv)) {
            ReplayRecipe rec = {.kind = REPLAY_COMPUTE,
                .state_size = sizeof r->local, .state = r->local,
                .code = {sv, NULL}, .words = {(uint32_t)nv, 0}};
            good = replay_get(&rec, NULL) != NULL;
        }
        goto complete;
    }
    if (r->ncolor > 8 || r->nattrib > 16 || r->nstream > 16 ||
        !vsb || !fsb || !vsb->code || !fsb->code) goto complete;
    vk.flip_y = fk.flip_y = (r->flags & SR_FLIP_Y) != 0;
    vk.flip_x = fk.flip_x = (r->flags & SR_FLIP_X) != 0;
    vk.depth_minus_one = (r->flags & SR_DEPTH_MINUS_ONE) != 0;
    for (unsigned i = 0; i < r->nattrib; ++i)
        vk.attr_kind[i] = (uint8_t)attr_kind(r->attrib[i] & 255);
    for (unsigned i = 0; i < r->ncolor; ++i)
        fk.rt_kind[i] = (uint8_t)rt_kind(r->color[i]);
    if (!headstart_translate(vsb, STAGE_VERTEX, &vk, &vi, &sv, &nv)) goto complete;
    fk.vs_out_mask = vi->out_mask;
    if (!headstart_translate(fsb, STAGE_FRAGMENT, &fk, &fi, &sf, &nf)) goto complete;

    PipeKey k = {0};
    k.ncolor = r->ncolor;
    k.samples = r->samples ? r->samples : 1;
    k.topo_class = r->topo;
    k.poly_fill = r->poly_fill;
    k.a2c = r->a2c;
    for (unsigned i = 0; i < k.ncolor; ++i) {
        if (!r->color[i]) continue;
        VkFormat fmt = vk_format(r->color[i]);
        if (fmt == VK_FORMAT_UNDEFINED) continue;
        k.color[i] = r->cview[i] ? vk_format(r->cview[i]) : fmt;
        k.write_mask[i] = ((fi->out_mask >> (i * 4)) & 15) ?
                            ((r->channel_mask >> (i * 4)) & 15) : 0;
        if (((r->blend_on >> i) & 1) && !rt_kind(r->color[i])) {
            k.blend_on |= (uint8_t)(1u << i);
            memcpy(k.blend[i], r->blend[i], 8);
        }
    }
    if (r->depth && renderer_format_is_depth(r->depth)) {
        VkFormat fmt = vk_format(r->depth);
        if (fmt != VK_FORMAT_UNDEFINED) {
            k.depth = fmt;
            if (renderer_format_has_stencil(r->depth)) k.stencil = fmt;
        }
    }
    for (unsigned i = 0; i < 32; ++i) {
        if (!(vi->attr_mask & (1u << i))) continue;
        k.attr_mask |= 1u << i;
        uint32_t a = i < r->nattrib ? r->attrib[i] : 0x2e;
        unsigned fmt = a & 255, stream = (a >> 8) & 31;
        if (i >= r->nattrib || !fmt || stream >= 16) {
            k.attr_fmt[i] = VK_FORMAT_R32G32B32A32_SFLOAT;
            k.attr_bind[i] = ZERO_BINDING;
            k.used_streams |= 1u << ZERO_BINDING;
        } else {
            k.attr_fmt[i] = vertex_format_supported(vertex_format(fmt));
            k.attr_off[i] = a >> 13;
            k.attr_bind[i] = stream;
            k.used_streams |= 1u << stream;
        }
    }
    for (unsigned s = 0; s < 16; ++s) {
        if (!(k.used_streams & (1u << s))) continue;
        k.stride[s] = s < r->nstream ? r->stream[s][0] : 0;
        k.divisor[s] = s < r->nstream && k.stride[s] ? r->stream[s][1] : 0;
        if (k.divisor[s] > 1 && !g_vk.divisor) k.divisor[s] = 1;
    }
    ReplayRecipe rec = {.kind = REPLAY_GRAPHICS,
        .state_size = PIPE_STATE_SIZE, .state = k.color,
        .code = {sv, sf}, .words = {(uint32_t)nv, (uint32_t)nf}};
    good = replay_get(&rec, NULL) != NULL;

complete:
    if (vi) maxwell_free(vi);
    if (fi) maxwell_free(fi);
    free(sv);
    free(sf);
    if (good) ++las_headstart_ready; else ++las_headstart_failed;
    return good;
}
