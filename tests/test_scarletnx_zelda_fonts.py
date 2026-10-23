#!/usr/bin/env python3
"""Offline regression for ScarletNX DejaVu font-only backport."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("font_backport", BASE / "tools/patch_scarletnx_zelda_fonts.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
license_file = BASE / "android/licenses/DejaVu-LICENSE.txt"


class FontPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)
        self.originals = {}
        for rel, pairs in mod.PATCHES.items():
            p = self.source / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            before = "\n".join(old for old, _ in pairs) + "\n"
            p.write_text(before)
            self.originals[p] = before

    def test_apply_and_revert(self):
        mod.run(self.source, license_file, False)
        mod.run(self.source, license_file, False)
        self.assertIn("DejaVu Sans 2.37", (self.source / "cmake/shared_fonts.cmake").read_text())
        self.assertTrue((self.source / "dist/licenses/DejaVu/LICENSE").is_file())
        mod.run(self.source, license_file, True)
        mod.run(self.source, license_file, True)
        for p, value in self.originals.items():
            self.assertEqual(p.read_text(), value)
        self.assertFalse((self.source / "dist/licenses/DejaVu/LICENSE").exists())

    def test_reject_unknown_revision_without_writing(self):
        p = self.source / "cmake/dependencies.cmake"
        p.write_text(p.read_text().replace("NAME OpenSans", "NAME Unknown"))
        snapshot = {p: p.read_text() for p in self.originals}
        with self.assertRaises(ValueError):
            mod.run(self.source, license_file, False)
        self.assertEqual(snapshot, {p: p.read_text() for p in self.originals})


if __name__ == "__main__":
    unittest.main()
