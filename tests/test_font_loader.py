#!/usr/bin/env python3
"""Decode synthetic BFTTF files wrapping the repository's open-source Roboto.

No Nintendo font or firmware files are needed. Tests call the real pl.c loader.
Requires Clang (the runtime CPU helpers use Clang builtins). Set CC to override.
"""
import ctypes
import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROBOTO = (ROOT / "third_party/imgui/misc/fonts/Roboto-Medium.ttf").read_bytes()


def wrap(data, *, key=b"\x49\x62\x18\x06", legacy=False, size=None):
    size = len(data) if size is None else size
    # Independent encoding of BFTTF's big-endian header and XOR byte stream.
    plain = struct.pack(">I", 0x7F9A0218) + size.to_bytes(4, "little" if legacy else "big") + data
    plain += b"\0" * (-len(plain) % 4)
    return bytes(b ^ key[i % 4] for i, b in enumerate(plain))


class FontLoader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="las-font-build-")
        cls.addClassCleanup(cls.build.cleanup)
        library = Path(cls.build.name) / "font-test.so"
        compiler = shlex.split(os.environ.get("CC", "clang"))
        subprocess.run([*compiler, "-shared", "-fPIC", "-std=gnu11", "-O1", "-g", "-Wno-format",
                        "-D__ANDROID__", "-I" + str(ROOT / "runtime"),
                        str(ROOT / "tests/font_loader_harness.c"), "-o", str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        for name in ("font_test_load", "font_test_shared"):
            fn = getattr(cls.lib, name)
            fn.argtypes = [ctypes.c_char_p if name.endswith("load") else ctypes.c_uint,
                           ctypes.POINTER(ctypes.c_void_p)]
            fn.restype = ctypes.c_size_t
        cls.lib.font_test_decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        cls.lib.font_test_decode.restype = ctypes.c_size_t
        cls.lib.font_test_request.argtypes = [ctypes.c_uint, ctypes.c_uint]
        cls.lib.font_test_request.restype = ctypes.c_uint64
        cls.lib.font_test_set_allocation_hook.argtypes = [ctypes.c_void_p]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="las-font-case-")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.lib.font_test_reset)
        original_font = os.environ.pop("LARECOMP_FONT", None)
        def restore_font_override():
            if original_font is None:
                os.environ.pop("LARECOMP_FONT", None)
            else:
                os.environ["LARECOMP_FONT"] = original_font
        self.addCleanup(restore_font_override)

    def decode(self, data):
        buf = ctypes.create_string_buffer(data)
        size = self.lib.font_test_decode(buf, len(data))
        return size, buf.raw[:size]

    def load(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        out = ctypes.c_void_p()
        size = self.lib.font_test_load(os.fsencode(path), ctypes.byref(out))
        return ctypes.string_at(out, size) if size else None

    def test_standard_bfttf_header_round_trip(self):
        size, decoded = self.decode(wrap(ROBOTO))
        self.assertEqual(size, len(ROBOTO))
        self.assertEqual(decoded, ROBOTO)

    def test_alternate_xor_byte_order_and_legacy_length_remain_usable(self):
        for legacy in (False, True):
            for key in (b"\x49\x62\x18\x06", b"\x06\x18\x62\x49"):
                with self.subTest(legacy=legacy, key=key):
                    self.assertEqual(self.decode(wrap(ROBOTO, key=key, legacy=legacy))[1], ROBOTO)

    def test_declared_length_not_padding_is_returned_including_partial_word(self):
        data = ROBOTO + b"\x12\x34\x56"
        self.assertEqual(self.decode(wrap(data)), (len(data), data))
        self.assertEqual(self.decode(wrap(data)[:-1]), (len(data), data)) # no container padding

    def test_ambiguous_length_byte_orders_require_the_complete_sfnt(self):
        data = ROBOTO.ljust(3 * 65536, b"\0") # reversed size is also in bounds: 768
        for legacy in (False, True):
            self.assertEqual(self.decode(wrap(data, legacy=legacy)), (len(data), data))

    def test_invalid_lengths_and_truncated_header_rejected(self):
        for size in (0, len(ROBOTO) + 4096, 0xFFFFFFFF):
            self.assertEqual(self.decode(wrap(ROBOTO, size=size))[0], 0)
        for size in range(12):
            self.assertEqual(self.decode(wrap(ROBOTO)[:size])[0], 0)

    def test_production_loader_accepts_imported_bfttf_and_raw_ttf(self):
        self.assertEqual(self.load("imported.bfttf", wrap(ROBOTO)), ROBOTO)
        self.assertEqual(self.load("imported.ttf", ROBOTO), ROBOTO)

    def test_decoded_font_still_requires_valid_sfnt_table_bounds(self):
        bad = bytearray(ROBOTO)
        struct.pack_into(">I", bad, 12 + 8, 0xFFFFFFF0)
        self.assertIsNone(self.load("corrupt.bfttf", wrap(bad)))

    def test_shared_font_selection_prefers_imported_standard_and_extension(self):
        fonts = self.folder / "fonts"
        fonts.mkdir()
        (fonts / "nintendo_udsg-r_std_003.bfttf").write_bytes(wrap(ROBOTO))
        (fonts / "nintendo_ext_003.bfttf").write_bytes(wrap(ROBOTO + b"\0\0\0\0"))
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            for font_type in (0, 5):
                out = ctypes.c_void_p()
                size = self.lib.font_test_shared(font_type, ctypes.byref(out))
                expected = ROBOTO + (b"\0\0\0\0" if font_type == 5 else b"")
                self.assertEqual(ctypes.string_at(out, size), expected)
        finally:
            os.chdir(previous)

    def test_unusable_import_still_uses_existing_android_fallback(self):
        fonts = self.folder / "fonts"
        fonts.mkdir()
        (fonts / "nintendo_udsg-r_std_003.bfttf").write_bytes(wrap(ROBOTO, size=0))
        (fonts / "android_fallback.ttf").write_bytes(ROBOTO)
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            for font_type in (0, 5):
                out = ctypes.c_void_p()
                size = self.lib.font_test_shared(font_type, ctypes.byref(out))
                self.assertEqual(ctypes.string_at(out, size), ROBOTO)
        finally:
            os.chdir(previous)

    def test_parallel_first_requests_never_observe_partially_loaded_fonts(self):
        fonts = self.folder / "fonts"
        fonts.mkdir()
        (fonts / "android_fallback.ttf").write_bytes(ROBOTO)
        allocating, release = threading.Event(), threading.Event()
        completed = [threading.Event() for _ in range(3)]
        started = [threading.Event() for _ in range(3)]
        values, first, failures = {}, {}, []

        @ctypes.CFUNCTYPE(None)
        def pause_allocation():
            allocating.set()
            if not release.wait(5):
                failures.append("font allocation was never released")

        def initialize():
            out = ctypes.c_void_p()
            first["size"] = self.lib.font_test_shared(0, ctypes.byref(out))
            first["address"] = out.value

        def request(method):
            started[method].set()
            values[method] = self.lib.font_test_request(method, 5)
            completed[method].set()

        previous = Path.cwd()
        threads = []
        try:
            os.chdir(self.folder)
            self.lib.font_test_set_allocation_hook(pause_allocation)
            threads.append(threading.Thread(target=initialize))
            threads[-1].start()
            self.assertTrue(allocating.wait(3), "first font did not reach allocation")
            for method in range(3):
                thread = threading.Thread(target=request, args=(method,))
                threads.append(thread)
                thread.start()
            for event in started:
                self.assertTrue(event.wait(3))
            # The first allocation is still paused: no state/address/size call
            # may advertise a ready font or return a zero pointer/size here.
            early = [method for method, event in enumerate(completed) if event.wait(.05)]
        finally:
            release.set()
            for thread in threads:
                thread.join(3)
            self.lib.font_test_set_allocation_hook(None)
            os.chdir(previous)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures)
        self.assertEqual(early, [], "shared-font calls returned before initialization completed")
        self.assertEqual(values, {0: 1, 1: first["address"], 2: len(ROBOTO)})
        self.assertEqual(first["size"], len(ROBOTO))
        self.assertTrue(first["address"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
