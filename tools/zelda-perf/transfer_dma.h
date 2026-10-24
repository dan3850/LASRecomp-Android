/* SPDX-License-Identifier: MIT
 * Complete pitch-linear overwrites need neither a copy of the old destination
 * nor scratch rows. All other layouts keep the original DMA implementation.
 */
#ifndef SNX_TRANSFER_DMA_H
#define SNX_TRANSFER_DMA_H
static int snx_transfer_linear_dma(const GpuDmaOp* o) {
    if (!snx_transfer_on() || o->fill || o->remap || o->shuffle || o->keep ||
        o->src.bl || o->dst.bl || !o->lines || !o->line_out || o->line_in != o->line_out ||
        (o->lines != 1 && (o->src.pitch != o->line_in || o->dst.pitch != o->line_out))) return -1;
    u64 size = (u64)o->line_out * o->lines, at;
    if (size > g_vk.alloc_cap || size > ~o->src.addr || size > ~o->dst.addr) return -1;
    VkOwnRes* d = vk_own_res_new(size);
    if (!d) return 0;
    vk_render_end();
    VkBuffer src;
    u8* p;
    if (o->snap) {
        p = vk_stage(size, vk_stage_align(), &src, &at);
        if (p) memcpy(p, o->snap, size);
    } else p = stage_range(o->src.addr, size, &src, &at);
    if (!p) { vk_own_res_unref(d); return 0; }
    VkCommandBuffer cb = vk_cmd();
    vk_all_barrier(cb); /* keep producer visibility, including stage_range overlays */
    VkBufferCopy region = {at, 0, size};
    rec_CmdCopyBuffer(cb, src, d->buf, 1, &region);
    vk_all_barrier(cb);
    for (u64 off = 0; off < size;) {
        u64 cpu = 0, n = gmmu_run(o->dst.addr + off, size - off, &cpu);
        if (!n) {
            n = 0x1000 - ((o->dst.addr + off) & 0xFFF);
            if (n > size - off) n = size - off;
        } else vk_own_publish(cpu, n, d, off);
        off += n;
    }
    gpu_mem_written(o->dst.addr, size);
    vk_own_res_unref(d);
    snx_transfer_note(SNX_XFER_LINEAR, 1);
    snx_transfer_note(SNX_XFER_LINEAR_BYTES, size);
    snx_transfer_note(SNX_XFER_DST_BYTES, size);
    return 1;
}
#endif
