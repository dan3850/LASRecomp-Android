#!/usr/bin/env python3
"""Apply validated Host1x submit relocations to copied command words.

Experimental ScarletNX source patch. Reversible; never edits upstream checkout
unless explicitly invoked by the Castlevania build script.
"""
import argparse
from pathlib import Path

OLD = '    if (nrel) WARN_LIMIT(1, "host1x: a submit\'s %u relocations are not applied\\n", nrel);'
NEW = '    /* Relocations are applied to the copied job below, not guest memory. */'
ANCHOR = '    free(addr);\n    for (i = 0; i < ninc; i++, k += 2) {'
PATCH = r"""    /* Relocation entries: {cmdbuf handle, byte offset, target handle, target byte offset},
       followed by one u32 shift per entry. Resolve through the existing IOVA mapper.
       Only patch the private command-stream copy; guest nvmap memory is untouched. */
    for (i = 0; i < nrel; i++) {
        u64 at = o_cb + 12ull * ncb + 16ull * i;
        u32 src_handle = rd32(d, (u32)at);
        u32 src_off = rd32(d, (u32)at + 4);
        u32 dst_handle = rd32(d, (u32)at + 8);
        u32 dst_off = rd32(d, (u32)at + 12);
        u32 shift = rd32(d, (u32)(o_cb + 12ull * ncb + 16ull * nrel + 4ull * i));
        u32 dst_base = 0, dst_size = 0, j, word_at = 2;
        u64 dst_addr = 0;
        int found = 0;
        if ((src_off & 3u) || shift >= 32 || !nvmap_get(dst_handle, &dst_addr, &dst_size) ||
            !dst_addr || dst_off >= dst_size || iova_map(dst_handle, &dst_base) != NV_OK ||
            (u64)dst_base + dst_off > 0xffffffffull) {
            WARN_LIMIT(8, "host1x: invalid relocation %u (source %u, target %u)\n",
                       i, src_handle, dst_handle);
            free(job);
            free(addr);
            return NV_BAD_PARAMETER;
        }
        for (j = 0; j < ncb; j++) {
            u32 cb_at = (u32)(o_cb + 12ull * j);
            u32 cb_handle = rd32(d, cb_at);
            u32 cb_off = rd32(d, cb_at + 4);
            u32 words = job[word_at++];
            if (cb_handle == src_handle && src_off >= cb_off &&
                (u64)src_off + 4 <= (u64)cb_off + 4ull * words) {
                job[word_at + (src_off - cb_off) / 4] =
                    (u32)(((u64)dst_base + dst_off) >> shift);
                found = 1;
                break;
            }
            word_at += words;
        }
        if (!found) {
            WARN_LIMIT(8, "host1x: relocation %u source outside submitted command buffers\n", i);
            free(job);
            free(addr);
            return NV_BAD_PARAMETER;
        }
    }
"""
# addr is freed before the patch location in upstream; move the free afterward.
BEFORE = '    free(addr);\n    for (i = 0; i < ninc; i++, k += 2) {'
AFTER = PATCH + '    free(addr);\n    for (i = 0; i < ninc; i++, k += 2) {'

def apply(source, revert):
    if revert:
        if source.count(AFTER) != 1 or source.count(NEW) != 1:
            raise ValueError("Host1x relocation patch missing or modified")
        return source.replace(AFTER, BEFORE, 1).replace(NEW, OLD, 1)
    if source.count(BEFORE) != 1 or source.count(OLD) != 1:
        raise ValueError("Unexpected Host1x source: refusing unsafe patch")
    return source.replace(BEFORE, AFTER, 1).replace(OLD, NEW, 1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    file = Path(args.source) / "src/nx/gpu/video/host1x.c"
    source = file.read_text()
    updated = apply(source, args.revert)
    file.write_text(updated)
    print("Host1x relocation patch", "reverted" if args.revert else "applied")

if __name__ == "__main__":
    main()
