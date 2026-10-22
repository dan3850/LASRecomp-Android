#!/usr/bin/env python3
"""Termux ABI 2 identity, signed-APK integrity and shared-source restoration."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent


def restore(root):
    spec = importlib.util.spec_from_file_location('runtime_v2_patch', HERE / 'ryujinx-nativeaot/patch_runtime_v2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    updated = {}
    for name, pairs in module.replacements().items():
        path = root / name
        text = path.read_text()
        for old, new in reversed(pairs):
            if text.count(new) == 1:
                text = text.replace(new, old, 1)
            elif text.count(old) != 1:
                raise ValueError('cannot safely restore modified source: ' + name)
        updated[path] = text
    for path, text in updated.items():
        if path.read_text() != text:
            path.write_text(text)
    for name in ('snx_ryu_runtime_v2.h', 'snx_ryu_support_v2.h', 'snx_ryu_expected.h'):
        (root / 'src/nx/gpu/vk' / name).unlink(missing_ok=True)
    print('ABI 2: shared ScarletNX sources restored')


def expected_identity(path):
    value = json.loads(path.read_text())['source_identity']
    if not value.startswith('SNX_RYU_SOURCE_SHA256=') or len(value.split('=')[1]) != 64:
        raise ValueError('invalid source identity')
    return value


def verify_library(library, identity):
    expected = expected_identity(identity)
    lib = ctypes.CDLL(str(library.resolve()))
    lib.snx_ryu_build_identity.restype = ctypes.c_char_p
    actual = lib.snx_ryu_build_identity().decode()
    if actual != expected:
        raise ValueError(f'stale NativeAOT: expected {expected}, got {actual}')
    getattr(lib, 'snx_ryu_translate_scarlet_v2')
    print('NATIVE_V2_IDENTITY_OK:', actual)


def verify_apk(apk, identity, revision, library):
    with zipfile.ZipFile(apk) as archive:
        runtime = archive.read('lib/arm64-v8a/libscarletnx.so')
        native = archive.read('lib/arm64-v8a/libRyujinxShaderNative.so')
    if hashlib.sha256(native).digest() != hashlib.sha256(library.read_bytes()).digest():
        raise ValueError('signed APK contains a different NativeAOT library')
    for marker in (expected_identity(identity), revision, 'RYUJINX_NATIVE_V2'):
        if marker.encode() not in runtime:
            raise ValueError('signed APK contains a stale runtime: missing ' + marker)
    print('SIGNED_APK_V2_OK:', apk)
    print('APK_SHA256:', hashlib.sha256(apk.read_bytes()).hexdigest())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path', type=Path)
    ap.add_argument('--revert', action='store_true')
    ap.add_argument('--identity', type=Path)
    ap.add_argument('--revision')
    ap.add_argument('--library', type=Path)
    args = ap.parse_args()
    if args.revert:
        restore(args.path)
    elif args.identity and args.revision and args.library:
        verify_apk(args.path, args.identity, args.revision, args.library)
    elif args.identity:
        verify_library(args.path, args.identity)
    else:
        ap.error('--identity required')


if __name__ == '__main__':
    main()
