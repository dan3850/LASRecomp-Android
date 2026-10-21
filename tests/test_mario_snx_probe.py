#!/usr/bin/env python3
"""ABI-12 layout test for independent LASRecomp Android ScarletNX load probe."""
import ctypes
import unittest


class SnxModule(ctypes.Structure):
    _fields_ = [
        ("abi", ctypes.c_uint32),
        ("nmods", ctypes.c_uint32),
        ("mods", ctypes.c_void_p),
        ("nentries", ctypes.c_uint32),
        ("entry_addr", ctypes.c_void_p),
        ("entry_fn", ctypes.c_void_p),
        ("interp", ctypes.c_void_p),
        ("code_lo", ctypes.c_uint64),
        ("code_hi", ctypes.c_uint64),
        ("title", ctypes.c_void_p),
        ("title_id", ctypes.c_uint64),
        ("main_stack", ctypes.c_uint32),
        ("main_prio", ctypes.c_uint32),
        ("main_core", ctypes.c_uint32),
    ]


class TestSnxAbi12(unittest.TestCase):
    def test_module_layout(self):
        self.assertEqual(ctypes.sizeof(SnxModule), 96)
        offsets = dict(
            abi=0, nmods=4, mods=8, nentries=16, entry_addr=24,
            entry_fn=32, interp=40, code_lo=48, code_hi=56,
            title=64, title_id=72, main_stack=80,
            main_prio=84, main_core=88,
        )
        for name, expected in offsets.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(SnxModule, name).offset, expected)

    def test_64bit_host(self):
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
