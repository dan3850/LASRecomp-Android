#!/usr/bin/env python3
"""Validate the production compute adapter/cache and dispatch its synthetic output on Vulkan."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--vulkan-include', type=Path)
    parser.add_argument('--loader-arg', default='-lvulkan')
    args = parser.parse_args()
    os.environ['SCARLETNX_TEST_SRC'] = str(args.source.resolve())
    spec = importlib.util.spec_from_file_location('nx_compute_test', ROOT / 'tests/test_zelda_perf_nx_compute.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    with tempfile.TemporaryDirectory(prefix='zelda-nxcompute-vulkan-') as d:
        out = Path(d)
        shader, reflection = helper.prepare(out)
        cache = out / 'cache'; cache.mkdir()
        subprocess.run(['cc', '-std=gnu11', '-D_GNU_SOURCE', '-O1', '-Wall', '-Wextra', '-Werror',
            '-I' + d, '-I' + str(args.source / 'src'), '-I' + str(ROOT / 'tools/zelda-perf'),
            str(ROOT / 'tests/zelda_nx_compute_fixture.c'),
            str(args.source / 'src/nx/runtime/driver/hactool/cJSON.c'), '-ldl', '-lm', '-o', str(out / 'adapt')], check=True)
        adapted = out / 'adapted.spv'
        subprocess.run([str(out / 'adapt'), str(shader), str(reflection), str(cache), str(adapted)], check=True)
        subprocess.run(['spirv-val', '--target-env', 'vulkan1.3', str(adapted)], check=True)
        command = ['cc', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror']
        if args.vulkan_include:
            command += ['-I' + str(args.vulkan_include)]
        command += [str(ROOT / 'tests/zelda_nx_compute_vulkan_fixture.c'), args.loader_arg, '-o', str(out / 'gpu')]
        subprocess.run(command, check=True)
        subprocess.run([str(out / 'gpu'), str(adapted)], check=True, timeout=60)


if __name__ == '__main__':
    main()
