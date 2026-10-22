#!/usr/bin/env python3
"""Synthetic corpus tests. Never add real game shader captures to this repo."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "tools/castlevania_ryujinx_probe.py"
spec = importlib.util.spec_from_file_location("castlevania_ryujinx_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def corpus(path, stage=4, info_size=192, code=None, version=1):
    if code is None:
        code = bytes(80 + 8 * 16)
    path.write_bytes(struct.pack("<4sIIIII", b"SNXS", version,
                                 info_size, stage, len(code), len(code)) +
                     bytes(info_size) + code)


class RyujinxProbeTest(unittest.TestCase):
    def test_prepare_fragment_program_without_corrupting_input(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            capture = root / "captures"
            capture.mkdir()
            name = "0123456789abcdef_4.snxs"
            original = capture / name
            code = bytes(range(256))
            corpus(original, code=code)
            source_copy = original.read_bytes()
            jobs, errors = probe.prepare(capture, root / "result")
            self.assertEqual(errors, [])
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["stage"], "ps")
            self.assertEqual(Path(jobs[0]["code"]).read_bytes(), code)
            self.assertEqual(original.read_bytes(), source_copy)
            self.assertEqual(json.loads((root / "result/jobs.json").read_text()), jobs)

    def test_default_only_prepares_fragment_stage(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            capture = root / "captures"
            capture.mkdir()
            for stage in (0, 4, 5):
                corpus(capture / f"aaaaaaaaaaaaaaaa_{stage}.snxs", stage=stage)
            jobs, errors = probe.prepare(capture, root / "out")
            self.assertEqual(errors, [])
            self.assertEqual([x["stage"] for x in jobs], ["ps"])

    def test_rejects_partial_capture(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            p = root / "0123456789abcdef_4.snxs"
            corpus(p)
            p.write_bytes(p.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "truncated or trailing"):
                probe.read_corpus(p)

    def test_rejects_unsupported_stage(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "0123456789abcdef_2.snxs"
            corpus(p, stage=2)
            with self.assertRaisesRegex(ValueError, "not supported"):
                probe.read_corpus(p)

    def test_rejects_invalid_version(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "0123456789abcdef_4.snxs"
            corpus(p, version=2)
            with self.assertRaisesRegex(ValueError, "magic/version"):
                probe.read_corpus(p)


if __name__ == "__main__":
    unittest.main()
