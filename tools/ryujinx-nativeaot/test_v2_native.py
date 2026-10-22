#!/usr/bin/env python3
"""Exercise the real NativeAOT export with synthetic Maxwell, then spirv-val.
No game binaries, keys, captured shaders or game hashes are needed.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import struct
import subprocess

class Result(C.Structure):
    _fields_ = [(n, t) for n, t in [('spv', C.c_void_p), ('size', C.c_size_t),
        ('reflection', C.c_void_p), ('reflection_size', C.c_size_t), ('error', C.c_void_p), ('error_size', C.c_size_t)]]
class Meta(C.Structure):
    _fields_ = [('header', C.c_uint32 * 6), ('textures', C.c_uint32 * 512)]
QUERY = C.CFUNCTYPE(C.c_int, C.c_int, C.c_int, C.c_int, C.POINTER(C.c_uint32))

def shader(instructions):
    data = bytearray(512)
    struct.pack_into('<I', data, 0, 5 << 10)  # fragment SPH
    struct.pack_into('<I', data, 72, 15)  # RGBA output 0
    data[0x18] = 3  # location 0 screen-linear
    at = 80
    for i, op in enumerate(instructions):
        if i % 3 == 0:
            struct.pack_into('<Q', data, at, 0x001f8000fc0007e0); at += 8
        struct.pack_into('<Q', data, at, op); at += 8
    return bytes(data)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('library', type=Path); ap.add_argument('identity', type=Path)
    ap.add_argument('--out', type=Path, required=True); a = ap.parse_args(); a.out.mkdir(parents=True, exist_ok=True)
    lib = C.CDLL(str(a.library.resolve()))
    lib.snx_ryu_build_identity.restype = C.c_char_p
    expected = json.loads(a.identity.read_text())['source_identity']
    assert lib.snx_ryu_build_identity().decode() == expected, 'stale native library'
    translate = lib.snx_ryu_translate_scarlet_v2
    translate.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.POINTER(Result), C.POINTER(Meta), QUERY]
    translate.restype = C.c_int; lib.snx_ryu_free_v1.argtypes = [C.POINTER(Result)]
    calls = []
    @QUERY
    def query(kind, handle, slot, result):
        calls.append((kind, handle, slot)); result[0] = {0: 0, 1: 3, 2: 1, 3: 8, 5: 2}.get(kind, 0)
        return int(kind in (0, 1, 2, 3, 4, 5))
    mov = lambda r, v: 0x0100000000000000 | (v << 20) | 0x71000 | r
    exit_op = 0xe30000000007000f
    cases = {
        'solid': [mov(0, 0x3e800000), mov(1, 0x3f000000), mov(2, 0x3f400000), mov(3, 0x3f800000), exit_op],
        'texture-combined': [mov(0, 0x3e800000), mov(1, 0x3e800000),
            0xd800000000070000 | (1 << 53) | (255 << 28) | (1 << 20), exit_op],
        'fragcoord': [0xe000000000070000 | (0x1c << 30), mov(1, 0), mov(2, 0), mov(3, 0x3f800000), exit_op],
    }
    for name, instructions in cases.items():
        code = shader(instructions); job = b'{"stage":"ps","debug":true,"texture_buffer_index":2}'
        source = C.create_string_buffer(code); jobbuf = C.create_string_buffer(job); result = Result(); meta = Meta()
        try:
            rc = translate(source, len(code), jobbuf, len(job), C.byref(result), C.byref(meta), query)
            error = C.string_at(result.error, result.error_size).decode() if result.error else ''
            assert rc == 0, f'{name}: rc={rc}: {error}'
            assert meta.header[0] == 2 and meta.header[1] == 4
            path = a.out / (name + '.spv'); path.write_bytes(C.string_at(result.spv, result.size))
            subprocess.run(['spirv-val', '--target-env', 'vulkan1.3', str(path)], check=True)
            if name == 'texture-combined': assert meta.header[5] == 1 and meta.textures[4] == 0
            print('NATIVE_V2_OK:', name, result.size, 'bytes, textures:', meta.header[5], flush=True)
        finally: lib.snx_ryu_free_v1(C.byref(result))
    assert any(x[0] == 3 for x in calls), 'live alpha state not queried'
    # A missing GPU fact must not become an invented c1 value or 2D default.
    @QUERY
    def unavailable(kind, handle, slot, result): return 0
    result = Result(); meta = Meta(); code = C.create_string_buffer(shader(cases['solid'])); job = C.create_string_buffer(b'{"stage":"ps"}')
    try:
        assert translate(code, 512, job, len(job.value), C.byref(result), C.byref(meta), unavailable) == -2
        assert not result.spv and meta.header[0] == 0
    finally: lib.snx_ryu_free_v1(C.byref(result))
    print('NATIVE_V2_REGRESSIONS: 4 passed; identity verified; SPIR-V validated')

if __name__ == '__main__': main()
