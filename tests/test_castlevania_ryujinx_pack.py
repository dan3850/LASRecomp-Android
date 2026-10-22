#!/usr/bin/env python3
"""Synthetic-only private Ryujinx pack format test, no game data."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from package_castlevania_ryujinx_runtime import package


def inst(op, *args):
    return struct.pack("<" + "I" * (1 + len(args)),
                       ((len(args) + 1) << 16) | op, *args)


class PackTest(unittest.TestCase):
    def check_exact_source_pack_layout(self, count):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bridge = root / "bridge"
            bridge.mkdir()
            entries = []
            capture = root / "captured.zip"
            spv = struct.pack("<5I", 0x07230203, 0x00010300, 0, 50, 0)
            # Synthetic descriptor binding 2 = cbuf2, 34 = fragment sampler0.
            for var, binding in ((4, 34), (5, 2)):
                spv += inst(71, var, 34, 1) + inst(71, var, 33, binding)
            spv += inst(71, 2, 30, 0)
            spv += inst(59, 10, 2, 3) + inst(59, 11, 4, 0) + inst(59, 12, 5, 2)
            with zipfile.ZipFile(capture, "w") as archive:
                for index in range(count):
                    key = f"{index:016x}_4"
                    file = key + ".bridge.spv"
                    (bridge / file).write_bytes(spv)
                    code = bytes(96)
                    snxs = (struct.pack("<4sIIIII", b"SNXS", 1, 192, 4,
                                        len(code), 65536) + bytes(192) + code)
                    archive.writestr(f"shaders/{key}.snxs", snxs)
                    entries.append({
                        "key": key, "file": file,
                        "bridge_sha256": hashlib.sha256(spv).hexdigest(),
                        "descriptor_map": [{"set": 1, "binding": 2},
                                           {"set": 1, "binding": 34}],
                        "constant_buffers": [{"binding": 1, "slot": 2}],
                        "textures": 1,
                        "texture_sources": [{
                            "target_binding": 34, "texture_cbuf": 2,
                            "sampler_cbuf": 2, "texture_word_offset": 94,
                            "sampler_word_offset": 352, "usage_flags": 0
                        }]
                    })
            (bridge / "bridge-manifest.json").write_text(json.dumps({
                "status": "OFFLINE_ONLY_DO_NOT_LOAD", "shaders": entries
            }))
            dest = root / "bridge.snxrbr"
            report = package(capture, bridge, dest)
            self.assertEqual(len(report), count)
            raw = dest.read_bytes()
            self.assertEqual(struct.unpack_from("<8sI", raw), (b"SNXRB001", count))
            header = struct.unpack_from("<16sIIIIII", raw, 12)
            self.assertEqual(header[1:], (96, len(spv), 1 << 2, 0, 1, 1))
            self.assertEqual(struct.unpack_from("<II", raw, 52), (94, 352))

    def test_five_shader_pack_unchanged(self):
        self.check_exact_source_pack_layout(5)

    def test_six_shader_pack(self):
        self.check_exact_source_pack_layout(6)


if __name__ == "__main__":
    unittest.main()
