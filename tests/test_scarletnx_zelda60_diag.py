#!/usr/bin/env python3
"""Validate the Zelda 60fps v3 build-id diagnostic can be reversed safely."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_scarletnx_zelda60_diag.py"
spec = importlib.util.spec_from_file_location("zelda60_diag", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Zelda60DiagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "src/nx/runtime/main.c"
        self.path.parent.mkdir(parents=True)
        self.base = '#include <stdio.h>\n' + module.ORIGINAL + '\n'
        self.path.write_text(self.base)

    def test_round_trip(self):
        module.run(self.root, False)
        module.run(self.root, False)
        self.assertEqual(self.path.read_text().count("ZELDA60_MAIN_BUILD_ID="), 1)
        self.assertIn("ZELDA60_PATCH_STATE=OFF", self.path.read_text())
        module.run(self.root, True)
        module.run(self.root, True)
        self.assertEqual(self.path.read_text(), self.base)

    def test_unknown_source_does_not_change(self):
        self.path.write_text("different upstream main.c")
        with self.assertRaises(ValueError):
            module.run(self.root, False)
        self.assertEqual(self.path.read_text(), "different upstream main.c")

if __name__ == "__main__":
    unittest.main()
