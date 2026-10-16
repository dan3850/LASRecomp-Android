#!/usr/bin/env python3
"""Exercise real C RomFS reads against romfs_build, using synthetic files only."""
import ctypes as C
import errno
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
OPEN = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_char_p, use_errno=True)


class RomfsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="lasrecomp-romfs-test-")
        lib = Path(cls.build.name) / "romfs.so"
        subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g",
                        "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror", "-pthread",
                        str(ROOT / "runtime/romfs_virtual.c"),
                        str(ROOT / "runtime/romfs_build.c"), "-o", str(lib)], check=True)
        cls.lib = C.CDLL(str(lib), use_errno=True)
        cls.lib.romfs_virtual_create.argtypes = [C.c_char_p, C.c_size_t, OPEN, C.c_void_p, C.c_char_p, C.c_size_t]
        cls.lib.romfs_virtual_create.restype = C.c_void_p
        cls.lib.romfs_virtual_size.argtypes = [C.c_void_p]
        cls.lib.romfs_virtual_size.restype = C.c_uint64
        cls.lib.romfs_virtual_read.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint64]
        cls.lib.romfs_virtual_read.restype = C.c_ssize_t
        cls.lib.romfs_virtual_close.argtypes = [C.c_void_p]
        cls.lib.romfs_build.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_char_p, C.c_size_t]
        cls.lib.romfs_build.restype = C.c_bool

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lasrecomp-original-files-")
        self.root = Path(self.temp.name) / "romfs"
        self.root.mkdir()
        self.handles = []
        self.callbacks = []
        self.open_count = 0

    def tearDown(self):
        for handle in self.handles:
            self.lib.romfs_virtual_close(handle)
        self.temp.cleanup()

    def write(self, path, data):
        f = self.root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)

    def manifest(self):
        records = []
        for p in self.root.rglob("*"):
            name = p.relative_to(self.root).as_posix()
            if any(part.startswith(".") for part in p.relative_to(self.root).parts):
                continue
            records.append(f"D\t{name}\n" if p.is_dir() else f"F\t{p.stat().st_size}\t{name}\n")
        random.Random(7).shuffle(records)  # provider ordering must not matter
        return "".join(records).encode()

    def mount(self, manifest=None, opener=None):
        def open_file(_ctx, name):
            self.open_count += 1
            try:
                return os.open(self.root / os.fsdecode(name), os.O_RDONLY)
            except OSError as e:
                C.set_errno(e.errno)
                return -1
        callback = OPEN(opener or open_file)
        self.callbacks.append(callback)
        manifest = self.manifest() if manifest is None else manifest
        why = C.create_string_buffer(512)
        handle = self.lib.romfs_virtual_create(manifest, len(manifest), callback, None, why, len(why))
        if handle:
            self.handles.append(handle)
        return handle, why.value.decode()

    def read(self, handle, offset, size):
        out = C.create_string_buffer(size)
        result = self.lib.romfs_virtual_read(handle, out, size, offset)
        return result, out.raw

class VirtualRomfsTests(RomfsTestCase):
    def test_identical_to_existing_image_builder_and_random_reads(self):
        for name, data in {"root.bin": b"hello", "a/a.bin": b"a" * 33,
                           "a/deep/test.bin": bytes(range(256)) * 19,
                           "b/z.bin": b"tail", "a/zero": b"", "zero-last": b"",
                           "utf8/ação_日本_🎮.bin": "conteúdo".encode()}.items():
            self.write(name, data)
        (self.root / "empty/also-empty").mkdir(parents=True)
        self.write(".ignored", b"hidden")
        image = Path(self.temp.name) / "reference.bin"
        why = C.create_string_buffer(512)
        self.assertTrue(self.lib.romfs_build(os.fsencode(self.root), os.fsencode(image), None, why, len(why)), why.value)
        expected = image.read_bytes()
        handle, why = self.mount()
        self.assertTrue(handle, why)
        self.assertEqual(self.open_count, 0, "mount must not read/copy payloads")
        self.assertEqual(self.lib.romfs_virtual_size(handle), len(expected))
        self.assertEqual(self.read(handle, 0, len(expected)), (len(expected), expected))
        rng = random.Random(28)
        for _ in range(1200):
            start = rng.randrange(len(expected) + 1)
            size = rng.randrange(min(1024, len(expected) - start) + 1)
            self.assertEqual(self.read(handle, start, size), (size, expected[start:start + size]))

    def test_sparse_original_above_4gb_without_image_or_copy(self):
        p = self.root / "big.bin"
        big_size = 5_900_000_123
        with p.open("wb") as f:
            f.truncate(big_size)
            f.seek(big_size - 4)
            f.write(b"TAIL")
        handle, why = self.mount()
        self.assertTrue(handle, why)
        header = self.read(handle, 0, 80)[1]
        words = struct.unpack("<10Q", header)
        self.assertGreater(words[1], 2 ** 32)
        self.assertEqual(self.read(handle, 0x200 + big_size - 4, 4), (4, b"TAIL"))
        self.assertEqual(self.read(handle, words[7], 32)[0], 32)
        self.assertEqual({p.name for p in Path(self.temp.name).iterdir()}, {"romfs"})
        self.assertLess(p.stat().st_blocks * 512, 1 << 20)

    def test_lru_cache_concurrent_reads_and_close(self):
        for i in range(75):
            self.write(f"{i:03d}", bytes([i]) * 17)
        before = len(os.listdir("/proc/self/fd"))
        handle, why = self.mount()
        self.assertTrue(handle, why)
        def reads(worker):
            for j in range(250):
                i = (j * 19 + worker) % 75
                self.assertEqual(self.read(handle, 0x200 + i * 32, 17), (17, bytes([i]) * 17))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(reads, range(4)))
        self.assertLessEqual(len(os.listdir("/proc/self/fd")), before + 32)
        self.lib.romfs_virtual_close(handle)
        self.handles.remove(handle)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_malformed_indexes_rejected(self):
        cases = [b"", b"F\t1\ta", b"F\t-1\ta\n", b"F\t1\t../x\n", b"F\t1\t/x\n",
                 b"F\t1\tx/\n", b"F\t1\tx//y\n", b"F\t1\tx\x00\n", b"F\t1\tx\r\n",
                 b"F\t1\tx\nF\t1\tx\n", b"F\t1\td/x\n", b"D\td\nF\t1\td\n",
                 b"F\t9223372036854775807\tx\n", b"F\t184467440737095516160\tx\n",
                 b"D\tonly-empty-directory\n", b"F\t1\t" + b"x" * 256 + b"\n"]
        for case in cases:
            with self.subTest(index=case[:80]):
                handle, why = self.mount(case)
                self.assertFalse(handle)
                self.assertTrue(why)

    def test_missing_permission_and_pipe_errors(self):
        self.write("a", b"abc")
        for code in [errno.ENOENT, errno.EACCES]:
            def fail(_ctx, _name):
                C.set_errno(code)
                return -1
            handle, why = self.mount(opener=fail)
            self.assertTrue(handle, why)
            self.assertEqual(self.read(handle, 0x200, 3)[0], -1)
            self.assertEqual(C.get_errno(), code)
        def pipe(_ctx, _name):
            r, w = os.pipe()
            os.close(w)
            return r
        handle, why = self.mount(opener=pipe)
        self.assertTrue(handle, why)
        self.assertEqual(self.read(handle, 0x200, 3)[0], -1)
        self.assertEqual(C.get_errno(), errno.ESPIPE)

    def test_file_changed_or_short_read_is_error(self):
        self.write("a", b"abcdef")
        handle, why = self.mount()
        self.assertTrue(handle, why)
        self.assertEqual(self.read(handle, 0x200, 3), (3, b"abc"))
        self.write("a", b"ab")
        self.assertEqual(self.read(handle, 0x200, 6)[0], -1)
        self.assertEqual(C.get_errno(), errno.EIO)
        handle, why = self.mount(b"F\t6\ta\n")
        self.assertTrue(handle, why)
        self.assertEqual(self.read(handle, 0x200, 6)[0], -1)
        self.assertEqual(C.get_errno(), errno.EIO)

    def test_bounds_zero_length_and_overflow(self):
        self.write("a", b"a")
        handle, why = self.mount()
        self.assertTrue(handle, why)
        size = self.lib.romfs_virtual_size(handle)
        self.assertEqual(self.read(handle, size, 0)[0], 0)
        for off, length in [(size, 1), (size + 1, 0), (2 ** 64 - 1, 2), (0, size + 1)]:
            self.assertEqual(self.read(handle, off, length)[0], -1)
            self.assertEqual(C.get_errno(), errno.EINVAL)


class StorageIntegrationTests(RomfsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lib = Path(cls.build.name) / "storage.so"
        compiler = os.environ.get("CC", "clang")
        subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-shared", "-fPIC", "-pthread",
                        "-Wno-format", "-Werror=implicit-function-declaration",
                        str(ROOT / "tests/fs_storage_harness.c"),
                        str(ROOT / "runtime/romfs_virtual.c"), "-o", str(lib)], check=True)
        cls.storage = C.CDLL(str(lib), use_errno=True)
        cls.storage.test_mount.argtypes = [C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_int]
        cls.storage.test_mount.restype = C.c_uint32
        cls.storage.test_storage_size.restype = C.c_uint64
        cls.storage.test_storage_read.argtypes = [C.c_void_p, C.c_uint64, C.c_uint64, C.c_uint64]
        cls.storage.test_storage_read.restype = C.c_uint32

    def setUp(self):
        super().setUp()
        self.local = Path(self.temp.name) / "private"
        self.local.mkdir()
        self.write("region_common/test", b"original data")
        self.manifest_bytes = self.manifest()
        self.seed_bytes = None
        self.local_bytes = os.fsencode(self.local)
        self.external_bytes = os.fsencode(Path(self.temp.name))

    def tearDown(self):
        self.storage.test_unmount()
        super().tearDown()

    def mount_storage(self, directory=True, seed=None, error=0):
        if directory:
            (self.local / ".external-romfs-directory").write_text("content://test/tree/fixture")
        self.manifest_bytes = self.manifest()
        self.seed_bytes = os.fsencode(seed) if seed else None
        return self.storage.test_mount(self.local_bytes, self.external_bytes,
                                       self.manifest_bytes, self.seed_bytes, error)

    def storage_read(self, off, size, capacity=None):
        capacity = size if capacity is None else capacity
        out = C.create_string_buffer(capacity)
        return self.storage.test_storage_read(out, capacity, off, size), out.raw

    def build_reference(self, where=None):
        image = where or Path(self.temp.name) / "romfs.bin"
        why = C.create_string_buffer(512)
        self.assertTrue(self.lib.romfs_build(os.fsencode(self.root), os.fsencode(image), None, why, len(why)), why.value)
        return image.read_bytes()

    def test_istorage_mount_without_local_romfs_or_image(self):
        handle, why = self.mount()
        self.assertTrue(handle, why)
        expected = self.read(handle, 0, self.lib.romfs_virtual_size(handle))[1]
        self.assertEqual(self.mount_storage(), 0)
        self.assertEqual(self.storage.test_storage_size(), len(expected))
        self.assertEqual(self.storage_read(0, len(expected)), (0, expected))
        self.assertFalse((self.local / "romfs.bin").exists())
        self.assertFalse((self.local / "romfs").exists())
        self.assertFalse((Path(self.temp.name) / "romfs.bin").exists())

    def test_istorage_legacy_local_and_external_images(self):
        expected = self.build_reference()
        self.assertEqual(self.mount_storage(directory=False), 0)
        self.assertEqual(self.storage_read(0, len(expected)), (0, expected))
        self.storage.test_unmount()
        (self.local / "romfs.bin").write_bytes(expected)
        self.assertEqual(self.mount_storage(directory=False), 0)
        self.assertEqual(self.storage_read(0, len(expected)), (0, expected))

    def test_istorage_errors_and_remount(self):
        self.assertNotEqual(self.mount_storage(error=errno.EACCES), 0)
        self.assertEqual(self.mount_storage(), 0)
        size = self.storage.test_storage_size()
        self.assertNotEqual(self.storage_read(size, 1)[0], 0)
        self.assertNotEqual(self.storage_read(0, 5, capacity=4)[0], 0)
        self.assertNotEqual(self.storage_read(2 ** 64 - 1, 2)[0], 0)
        (self.root / "region_common/test").unlink()
        self.assertNotEqual(self.storage_read(0x200, 3)[0], 0)
        self.write("region_common/test", b"new data")
        self.assertEqual(self.mount_storage(), 0)
        self.assertEqual(self.storage_read(0x200, 8), (0, b"new data"))

    @staticmethod
    def image_files(image):
        h = struct.unpack_from("<10Q", image)
        dirs, files = image[h[3]:h[3] + h[4]], {}
        def directory(o):
            if o == 0:
                return ""
            parent, = struct.unpack_from("<I", dirs, o)
            size, = struct.unpack_from("<I", dirs, o + 20)
            return directory(parent) + dirs[o + 24:o + 24 + size].decode() + "/"
        o = 0
        while o + 32 <= h[8]:
            p, sibling, data, size, chain, nl = struct.unpack_from("<IIQQII", image, h[7] + o)
            path = directory(p) + image[h[7] + o + 32:h[7] + o + 32 + nl].decode()
            files[path] = image[h[9] + data:h[9] + data + size]
            o += 32 + ((nl + 3) & ~3)
        return files

    def test_istorage_randomizer_overrides_and_added_files(self):
        seed = Path(self.temp.name) / "seed"
        (seed / "romfs/region_common").mkdir(parents=True)
        (seed / "romfs/region_common/test").write_bytes(b"replacement longer than original")
        (seed / "romfs/region_common/new-file").write_bytes(b"added file")
        for directory in [True, False]:
            with self.subTest(directory=directory):
                if not directory:
                    (self.local / ".external-romfs-directory").unlink()
                    self.build_reference()
                self.assertEqual(self.mount_storage(directory=directory, seed=seed), 0)
                size = self.storage.test_storage_size()
                result, image = self.storage_read(0, size)
                self.assertEqual(result, 0)
                self.assertEqual(self.image_files(image), {
                    "region_common/test": b"replacement longer than original",
                    "region_common/new-file": b"added file"})
                self.storage.test_unmount()

    def test_istorage_corrupt_image_rejected(self):
        (self.local / "romfs.bin").write_bytes(bytes(512))
        self.assertNotEqual(self.mount_storage(directory=False), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
