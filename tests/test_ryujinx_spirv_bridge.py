#!/usr/bin/env python3
"""Synthetic SPIR-V tests; no copyrighted game shader data enters Git."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import json

SOURCE = Path(__file__).resolve().parents[1] / "tools/ryujinx_spirv_bridge.py"
spec = importlib.util.spec_from_file_location("ryujinx_spirv_bridge", SOURCE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def spirv(module_field=5):
    def inst(op, *a):
        return (op, list(a))
    def name(id, value):
        binary = value.encode() + b"\0"
        binary += bytes((-len(binary)) % 4)
        return (5, [id] + list(struct.unpack(f"<{len(binary)//4}I", binary)))
    instructions = [
        (17, [1]), name(5, "support_buffer"), name(6, "fp_c2"),
        name(7, "fp_t_cb196610_1058005e"),
        inst(71, 5, 34, 0), inst(71, 5, 33, 0),
        inst(71, 6, 34, 0), inst(71, 6, 33, 5),
        inst(71, 7, 34, 0), inst(71, 7, 33, 1),
        inst(22, 3, 32), inst(21, 2, 32, 0),
        inst(43, 3, 15, 0x3f800000),
        inst(43, 2, 16, module_field),
        inst(59, 10, 5, 2), inst(59, 11, 6, 2), inst(59, 12, 7, 0),
        inst(65, 13, 20, 5, 16), inst(61, 3, 21, 20)]
    return bridge.encode([0x07230203, 0x00010300, 0, 100, 0], instructions)


def reflection():
    return {"key": "0123456789abcdef_4", "stage": "ps", "cbufs": [
        {"binding": 5, "slot": 2}], "sbufs": [], "images": [],
        "textures": [{"binding": 1, "type": 3, "format": "Unknown",
                      "cbuf_slot": 0x30002, "handle": 0x1058005e,
                      "array": 1, "separate": False, "flags": 2}]}


class SPIRVBridgeTest(unittest.TestCase):
    def test_remap_and_remove_support_buffer(self):
        patched, report = bridge.transform(spirv(), reflection())
        _, instructions = bridge.parse(patched)
        self.assertEqual(report["support_scale_replacements"], 1)
        self.assertTrue(any(op == 83 and a == [3, 21, 15] for op, a in instructions))
        self.assertFalse(any(op == 59 and a[1] == 5 for op, a in instructions))
        decorated = {}
        for op, a in instructions:
            if op == 71:
                decorated.setdefault(a[0], {})[a[1]] = a[2]
        self.assertEqual(decorated[6], {34: 1, 33: 2})
        self.assertEqual(decorated[7], {34: 1, 33: 34})

    def test_reject_other_support_field(self):
        with self.assertRaisesRegex(bridge.BridgeError, "field"):
            bridge.transform(spirv(module_field=4), reflection())

    def test_reject_incompatible_texture(self):
        bad = reflection()
        bad["textures"][0]["type"] = 4
        with self.assertRaisesRegex(bridge.BridgeError, "texture facts"):
            bridge.transform(spirv(), bad)

    def test_zip_manifest_without_binary_commits(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive = root / "local.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("0123456789abcdef_4.spv", spirv())
                z.writestr("0123456789abcdef_4.res.json", json.dumps(reflection()))
            data = bridge.prepare(archive, root / "out")
            self.assertEqual(len(data["shaders"]), 1)
            self.assertTrue((root / "out/bridge-manifest.json").is_file())
            self.assertEqual(data["shaders"][0]["texture_sources"][0]["texture_word_offset"], 94)
            self.assertEqual(data["shaders"][0]["texture_sources"][0]["sampler_word_offset"], 352)


if __name__ == "__main__":
    unittest.main()
