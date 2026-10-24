/* SPDX-License-Identifier: MIT
 * Vulkan adaptation of nxnative's persistent transfer resources. No Metal API.
 * All calls run under vk_lock; retiring resources runs after the frame fence.
 */
#ifndef SNX_TRANSFER_H
#define SNX_TRANSFER_H
enum {
    SNX_XFER_ROW_BEFORE, SNX_XFER_ROW_AFTER, SNX_XFER_LINEAR,
    SNX_XFER_LINEAR_BYTES, SNX_XFER_DST_BYTES, SNX_XFER_N
};
int snx_transfer_on(void);
void snx_transfer_note(unsigned counter, u64 amount);
void snx_transfer_report(u64 window);
void snx_transfer_frame(void);
u64 snx_transfer_reclaim(u64 want);
#endif
