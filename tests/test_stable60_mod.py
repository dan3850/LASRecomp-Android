#!/usr/bin/env python3
"""Synthetic NSO -> actual generator -> executable C; no proprietary game data."""
import ctypes
import ctypes.util
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("stable60", ROOT / "tools/apply-stable60-mod.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
ENTRY = mod.BASE + mod.OFFSETS[0] - 8
CALLEE = ENTRY + 0x40
CC = shlex.split(os.environ.get("CC", "clang"))


def fixture(root, *, branch=False, split=False, compressed=False):
    """Build an original-layout test NSO with the two real mod offsets."""
    main = root / "extracted/exefs/main"
    main.parent.mkdir(parents=True)
    image = bytearray(mod.OFFSETS[-1] + 0x100)
    struct.pack_into("<I", image, 4, 0x100)
    image[0x100:0x104] = b"MOD0"
    struct.pack_into("<I", image, 0x104, 0x40)  # empty DT_NULL at 0x140
    start = ENTRY - mod.BASE
    for at in range(start, len(image) - 3, 4):
        struct.pack_into("<I", image, at, mod.NOP)
    struct.pack_into("<I", image, start, 0x528000e8)  # mov w8, #7 (preserved)
    for n, offset in enumerate(mod.OFFSETS):
        if branch:
            word = 0x14000002  # b pc+8, skipping the following mov
            struct.pack_into("<I", image, offset + 4, 0x52800000 | (11 + n) << 5 | n)
        else:
            target = CALLEE + 0x10 * n
            word = 0x94000000 | (((target - mod.BASE - offset) // 4) & 0x3ffffff)
        struct.pack_into("<I", image, offset, word)
    for offset in (start + 0x1c, start + 0x3c):
        struct.pack_into("<I", image, offset, 0xd65f03c0 if split or offset == start + 0x3c else mod.NOP)
    header = bytearray(0x100)
    header[:4] = b"NSO0"
    header[0x40:0x60] = bytes.fromhex(mod.BUILD_ID).ljust(32, b"\0")
    payload = bytes(image)
    if compressed:
        # A valid LZ4 block with just one literal sequence, including extensions.
        n = len(payload) - 15
        payload = b"\xf0" + b"\xff" * (n // 255) + bytes([n % 255]) + payload
        struct.pack_into("<I", header, 0xc, 1)
    struct.pack_into("<III", header, 0x10, 0x100, 0, len(image))
    for index in (1, 2):
        struct.pack_into("<III", header, 0x10 + index * 16, 0x100 + len(payload), len(image), 0)
    struct.pack_into("<I", header, 0x60, len(payload))
    main.write_bytes(header + payload)
    nso = mod.read_nso(main)
    module = mod.Module("main", None, mod.BASE, "c", nso=nso)
    spans = [(ENTRY, ENTRY + 0x20), (ENTRY + 0x20, CALLEE)] if split else [(ENTRY, CALLEE)]
    folder = root / "build/gamecode/main"
    folder.mkdir(parents=True)
    helpers = (f"void f_{CALLEE:x}(Cpu *c) {{ c->x[1] += 30; }}\n"
               f"void f_{CALLEE+0x10:x}(Cpu *c) {{ c->x[2] += 60; }}\n"
               "volatile int g_fnprof;\nvoid fnprof_hit(uint64_t a, uint64_t b, uint64_t c) {}\n"
               '__attribute__((visibility("default"))) void test_run(uint64_t *out) {\n'
               f"Cpu c = {{0}}; c.x[30] = 0x12345678; c.nzcv = 0xa0000000; f_{ENTRY:x}(&c);\n"
               + (f"f_{ENTRY+0x20:x}(&c);\n" if split else "")
               + "out[0]=c.x[0]; out[1]=c.x[1]; out[2]=c.x[2]; out[3]=c.x[8]; "
                 "out[4]=c.x[30]; out[5]=c.nzcv; }\n")
    for index, (entry, end) in enumerate(spans):
        labels, _, tables = module.scan(entry, end)
        body = "\n".join(module.emit_function(entry, end, labels, tables, {}))
        text = '#include "cpu.h"\n#include "simd.h"\n'
        text += f"void f_{CALLEE:x}(Cpu *c);\nvoid f_{CALLEE+0x10:x}(Cpu *c);\n" + body + "\n"
        if not index:
            if split:
                # test_run appears after the second function's forward declaration.
                text += f"void f_{ENTRY+0x20:x}(Cpu *c);\n"
            text += helpers
        (folder / f"main_{index:03d}.c").write_text(text)
    starts = [entry for entry, _ in spans] + [CALLEE, CALLEE + 0x10]
    table = '#include "cpu.h"\n' + "".join(f"void f_{a:x}(Cpu *c);\n" for a in starts)
    table += "const uint64_t main_fn_addrs[] = {\n" + ",\n".join(f"0x{a:x}ull" for a in starts) + "};\n"
    table += "const GuestFn main_fn_ptrs[] = {" + ",".join(f"f_{a:x}" for a in starts) + "};\n"
    table += f"const uint64_t main_fn_count = {len(starts)};\n"
    (folder / "main_table.c").write_text(table)
    return main


class Stable60(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="las stable60 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_find_main_in_shared_storage_and_skip_wrong_build(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        shared = self.root / "storage/emulated/0"
        wrong = workspace / "extracted/exefs/main"
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(b"NSO0" + bytes(0x100))
        nsomain = shared / "Download/Zelda (Switch)/exefs/main"
        nsomain.parent.mkdir(parents=True)
        header = bytearray(0x100)
        header[:4] = b"NSO0"
        header[0x40:0x60] = bytes.fromhex(mod.BUILD_ID).ljust(32, b"\0")
        nsomain.write_bytes(header)
        originals = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (wrong, nsomain)}
        self.assertEqual(mod.find_nso(workspace, [workspace, shared]), nsomain.resolve())
        for path, expected in originals.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)

    def test_find_proot_nso_and_leave_cache_directories_unvisited(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        proot = self.root / "prefix/var/lib/proot-distro/installed-rootfs"
        main = proot / "ubuntu/root/LASRecomp/extracted/exefs/main.nso"
        main.parent.mkdir(parents=True)
        header = bytearray(0x100)
        header[:4] = b"NSO0"
        header[0x40:0x60] = bytes.fromhex(mod.BUILD_ID).ljust(32, b"\0")
        main.write_bytes(header)
        decoy = workspace / ".cache/exefs/main"
        decoy.parent.mkdir(parents=True)
        decoy.write_bytes(header)
        with patch.dict(os.environ, PREFIX=str(self.root / "prefix"),
                        EXTERNAL_STORAGE=str(self.root / "missing-shared")), \
             patch.object(mod.Path, "home", return_value=workspace):
            self.assertEqual(mod.find_nso(workspace), main.resolve())
        self.assertIsNone(mod.find_nso(workspace, [workspace]))

    def test_find_does_not_follow_directory_links_and_prefers_known_path(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        header = bytearray(0x100)
        header[:4] = b"NSO0"
        header[0x40:0x60] = bytes.fromhex(mod.BUILD_ID).ljust(32, b"\0")
        outside = self.root / "outside/main"
        outside.parent.mkdir()
        outside.write_bytes(header)
        (workspace / "loop").symlink_to(workspace, target_is_directory=True)
        (workspace / "linked").symlink_to(outside.parent, target_is_directory=True)
        self.assertIsNone(mod.find_nso(workspace, [workspace, self.root / "missing"]))
        known = workspace / "extracted/exefs/main"
        known.parent.mkdir(parents=True)
        known.write_bytes(header)
        self.assertEqual(mod.find_nso(workspace, []), known.resolve())

    def run_c(self, path, source):
        output = self.root / (path.stem + ("-mod" if "Stable 60fps" in source else "-original") + ".so")
        test_source = output.with_suffix(".c")
        test_source.write_text(source)
        subprocess.run([*CC, "-std=gnu11", "-O1", "-fPIC", "-shared", "-I" + str(ROOT / "runtime"),
                        str(test_source), "-o", str(output)], check=True, capture_output=True)
        lib = ctypes.CDLL(str(output))
        result = (ctypes.c_uint64 * 6)()
        lib.test_run(result)
        return tuple(result)

    def test_two_nops_remove_calls_and_lr_writes_without_touching_flags(self):
        nso = fixture(self.root)
        original_nso = nso.read_bytes()
        changes, words = mod.plan_sources(self.root, nso)
        self.assertEqual(len(changes), 1)
        path, patched = next(iter(changes.items()))
        before = path.read_text()
        self.assertEqual(self.run_c(path, before)[1:3], (30, 60))
        result = self.run_c(path, patched)
        self.assertEqual(result, (0, 0, 0, 7, 0x12345678, 0xa0000000))
        self.assertEqual(patched.count("Stable 60fps v2:"), 2)
        self.assertEqual(set(words), {"01019608", "01019628"})
        self.assertEqual(nso.read_bytes(), original_nso)
        self.assertEqual(path.read_text(), before)
        # Specifically reject the erroneous +0x100 header shift.
        self.assertNotIn("main+0x1019708", patched)

    def test_non_call_instructions_and_two_separate_chunks(self):
        nso = fixture(self.root, branch=True, split=True)
        changes, _ = mod.plan_sources(self.root, nso)
        self.assertEqual(len(changes), 2)
        original = "\n".join(path.read_text() for path in changes)
        patched = "\n".join(changes.values())
        self.assertEqual(self.run_c(Path("combined"), original)[:2], (0, 0))
        self.assertEqual(self.run_c(Path("combined"), patched)[:2], (11, 12))

    def test_wrong_build_id_and_edited_generated_function_are_refused(self):
        nso = fixture(self.root)
        raw = bytearray(nso.read_bytes()); raw[0x40] ^= 1; nso.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "Build ID"):
            mod.plan_sources(self.root, nso)
        raw[0x40] ^= 1; nso.write_bytes(raw)
        source = self.root / "build/gamecode/main/main_000.c"
        source.write_text(source.read_text().replace("FN_ENTER(", "/* local override */ FN_ENTER(", 1))
        edited = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "C nao corresponde"):
            mod.plan_sources(self.root, nso)
        self.assertEqual(source.read_bytes(), edited)
        self.assertFalse((self.root / "build/private-android-lasgame-termux").exists())

    def test_compressed_nso_and_bounded_lz4_repetitions(self):
        nso = fixture(self.root, compressed=True)
        changes, _ = mod.plan_sources(self.root, nso)
        self.assertEqual(sum(text.count("Stable 60fps v2:") for text in changes.values()), 2)
        self.assertEqual(mod.lz4_block(b"\x32abc\x03\x00", 9), b"abcabcabc")
        for data, size in [(b"\xf0", 16), (b"\x10x\0\0", 8), (b"\x10x\x02\0", 8),
                           (b"\x30abc", 2), (b"\x30ab", 3), (b"\x10x\x01", 5),
                           (b"\x10x\x01\0", 2), (b"\x10x", 2)]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                mod.lz4_block(data, size)

    @unittest.skipUnless(ctypes.util.find_library("lz4"), "needs system liblz4")
    def test_lz4_matches_reference_compression(self):
        lib = ctypes.CDLL(ctypes.util.find_library("lz4"))
        lib.LZ4_compressBound.argtypes = [ctypes.c_int]
        lib.LZ4_compress_default.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        for size in (1, 14, 15, 255, 4096, 65536):
            for data in (b"x" * size, bytes(range(256)) * (size // 256) + bytes(range(size % 256)), os.urandom(size)):
                source = ctypes.create_string_buffer(data)
                capacity = lib.LZ4_compressBound(size)
                output = ctypes.create_string_buffer(capacity)
                count = lib.LZ4_compress_default(source, output, size, capacity)
                self.assertGreater(count, 0)
                self.assertEqual(mod.lz4_block(output.raw[:count], size), data)

    @unittest.skipUnless(shutil.which("clang") and (shutil.which("llvm-nm") or shutil.which("nm")),
                         "needs clang and nm")
    def test_relink_reuses_original_objects_and_keeps_original_library(self):
        nso = fixture(self.root)
        runtime = self.root / "runtime"
        runtime.mkdir()
        for header in (ROOT / "runtime").glob("*.h"):
            shutil.copyfile(header, runtime / header.name)
        sdk = self.root / "build/gamecode/sdk"
        sdk.mkdir()
        (sdk / "sdk_table.c").write_text('#include "cpu.h"\nvoid sdk_stub(Cpu *c) {}\n'
            'const uint64_t sdk_fn_addrs[]={0x7004000000ull}, sdk_fn_count=1;\n'
            'const GuestFn sdk_fn_ptrs[]={sdk_stub};\n')
        tools = self.root / "tools"
        tools.mkdir()
        entry = tools / "gamelib_entry.c"
        shutil.copyfile(ROOT / "tools/gamelib_entry.c", entry)
        private = self.root / "build/private-android-lasgame-termux"
        objects = []
        sources = sorted(self.root.glob("build/gamecode/*/*.c")) + [entry]
        for source in sources:
            rel = source.relative_to(self.root / "build/gamecode") if source != entry else Path(source.name)
            obj = private / "objects" / rel.with_suffix(".o")
            obj.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([*CC, *mod.FLAGS, "-I" + str(runtime), "-c", str(source), "-o", str(obj)],
                           check=True, capture_output=True)
            objects.append(obj)
        library = private / "liblasgame.so"
        subprocess.run([*CC, "-shared", *map(str, objects), "-o", str(library)], check=True, capture_output=True)
        preserved = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in [*sources, *objects, library, nso]}
        changes, _ = mod.plan_sources(self.root, nso)
        output = private / "stable60-v2"
        actual_run = subprocess.run
        compiles = []

        def host_run(args, **kwargs):
            if args[0] == "clang":
                # Exercise production compile/link flow with host objects. This
                # does not claim Android/Bionic validation.
                if "-c" in args:
                    compiles.append(args[args.index("-c") + 1])
                args = [*CC, *[a for a in args[1:] if a not in ("-llog", "-landroid")]]
            return actual_run(args, **kwargs)

        with patch.object(mod.platform, "machine", return_value="aarch64"), \
             patch.dict(os.environ, PREFIX="/data/data/com.termux/files/usr"), \
             patch.object(mod, "check_object"), patch.object(mod.subprocess, "run", side_effect=host_run):
            patched = mod.build(self.root, changes, output)
            self.assertEqual(len(compiles), len(changes) + 1)  # changed chunk and tag ONLY
            compiles.clear()
            self.assertEqual(mod.build(self.root, changes, output), patched)
            self.assertFalse(compiles)  # repeated application reuses mod objects too
        loaded = ctypes.CDLL(str(patched))
        loaded.lasgame_mod_stable60_v2.restype = ctypes.c_char_p
        self.assertEqual(loaded.lasgame_mod_stable60_v2().decode(), mod.BUILD_ID)
        result = (ctypes.c_uint64 * 6)()
        loaded.test_run(result)
        self.assertEqual(tuple(result), (0, 0, 0, 7, 0x12345678, 0xa0000000))
        for path, (data, mtime) in preserved.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (data, mtime), str(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
