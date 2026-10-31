#!/usr/bin/env python3
"""Optional ScarletNX shader window backport (92fbbfa), single-program path only.

Keep dual-vertex merge at its proven 64 KiB size until merge bounds are audited.
No other pipeline or translator behavior is changed.
"""
import argparse
from pathlib import Path

OLD = """    u8* code = malloc(0x10000);
    if (!code) return NULL;
    gmem_read_code(gva, code, 0x10000);
    u32 len, len_a = 0;
    u64 qh, qh_a = 0;
    vk_shader_hash(code, 0x10000, &len, sh_cb_read);"""
NEW = """    /* Larger window only for single-program shaders; preserve dual-vertex merge ABI. */
    const u32 snx_shader_window = gva_a ? 0x10000u : 0x20000u;
    u8* code = malloc(snx_shader_window);
    if (!code) return NULL;
    gmem_read_code(gva, code, snx_shader_window);
    u32 len, len_a = 0;
    u64 qh, qh_a = 0;
    vk_shader_hash(code, snx_shader_window, &len, sh_cb_read);"""
TAIL = [
    ("vk_shader_hash(code, 0x10000, &mlen, sh_cb_read)",
     "vk_shader_hash(code, snx_shader_window, &mlen, sh_cb_read)"),
    ("shader_corpus_save(vk_corpus_dir(), code, mlen, 0x10000, stage",
     "shader_corpus_save(vk_corpus_dir(), code, mlen, snx_shader_window, stage"),
    ("vk_translate_spirv(code, 0x10000, stage",
     "vk_translate_spirv(code, snx_shader_window, stage"),
]

def apply(root: Path, revert: bool = False):
    path = root / "src/nx/gpu/vk/pipeline.c"
    data = path.read_text()
    pairs = [(OLD, NEW)] + TAIL
    if revert:
        pairs = [(new, old) for old, new in reversed(pairs)]
    if all(data.count(new) == 1 for _, new in pairs):
        return
    for old, new in pairs:
        if data.count(old) != 1:
            raise ValueError("Unknown pipeline layout or partial backport; source unchanged")
        data = data.replace(old, new, 1)
    path.write_text(data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    apply(args.source, args.revert)
