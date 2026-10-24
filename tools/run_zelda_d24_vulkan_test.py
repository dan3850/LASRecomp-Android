#!/usr/bin/env python3
"""Run the real D24 export component on a host Vulkan ICD, without game files.

Requires a clean pinned ScarletNX checkout, a C compiler, Vulkan headers/loader,
glslangValidator and spirv-val. Select an ICD via the ordinary Vulkan environment.
The extracted functions are the production code, not a rewritten conversion.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--vulkan-include', type=Path)
    p.add_argument('--cc', default='cc')
    p.add_argument('--glslang', default='glslangValidator')
    p.add_argument('--spirv-val', default='spirv-val')
    p.add_argument('--loader-arg', default='-lvulkan')
    args = p.parse_args()
    os.environ['SCARLETNX_TEST_SRC'] = str(args.source.resolve())
    spec = importlib.util.spec_from_file_location('d24_test_sources', ROOT / 'tests/test_zelda_perf_d24_pack.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory(prefix='zelda-d24-vulkan-') as d:
        out = Path(d)
        groups = (
            ('d24_tc_actual.inc', 'src/nx/gpu/vk/texconv.c', ('static void tc_init(', 'static int tc_dispatch(',
                'static u64 storage_align(', 'int vk_tc_d24_pack_supported(', 'int vk_tc_pack_d24(')),
            ('bl_move_actual.inc', 'src/nx/gpu/vk/blocklinear.c', ('static void bl_init(',
                'static u64 block_row_bytes(', 'static u64 slab_bytes(', 'void vk_bl_range(', 'int vk_bl_move(')),
            ('block_offsets_actual.inc', 'src/nx/gpu/gpu.c', ('static u64 bl_x(', 'static u64 bl_yz(', 'u64 bl_offset(')),
            ('rt_bl_move_actual.inc', 'src/nx/gpu/vk/surface.c', ('static u32 bl_height(', 'static VkBlMove rt_bl_move(')),
            ('surf_use_actual.inc', 'src/nx/gpu/vk/surface.c', ('void vk_surf_use(',)),
            ('bl_barrier_actual.inc', 'src/nx/gpu/vk/blocklinear.c', ('void vk_bl_barrier(',)),
        )
        for name, src, signatures in groups:
            text = m.patched(src)
            (out / name).write_text('\n'.join(m.HELPERS.function(text, n) for n in signatures))
        tc = m.prepare_glsl(out)
        for name in ('blocklinear.comp', 'blocklinear.glsl'):
            (tc.parent / name).write_text(m.source('src/nx/gpu/texture/' + name))
        for shader, spv in ((tc, out / 'tc.spv'), (tc.parent / 'blocklinear.comp', out / 'bl.spv')):
            subprocess.run([args.glslang, '-V', '--target-env', 'vulkan1.1', '-g0', '--spirv-val',
                            '-o', str(spv), str(shader)], check=True)
            subprocess.run([args.spirv_val, '--target-env', 'vulkan1.1', str(spv)], check=True)
        cmd = [args.cc, '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror', '-I'+d,
               '-I'+str(ROOT / 'tools/zelda-perf')]
        if args.vulkan_include: cmd += ['-I'+str(args.vulkan_include)]
        cmd += [str(ROOT / 'tests/zelda_d24_vulkan_fixture.c'), args.loader_arg, '-o', str(out / 'gpu')]
        subprocess.run(cmd, check=True)
        subprocess.run([str(out / 'gpu'), str(out / 'tc.spv'), str(out / 'bl.spv')], check=True, timeout=120)


if __name__ == '__main__': main()
