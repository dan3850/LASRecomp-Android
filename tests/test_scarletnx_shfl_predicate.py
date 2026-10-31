"""Regression tests for the conservative ScarletNX SHFL predicate backport."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_scarletnx_zelda_shfl_predicate.py"
spec = importlib.util.spec_from_file_location("shfl_patch", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ShflPredicatePatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "src/nx/gpu/shader/spirv_translate.c"
        self.path.parent.mkdir(parents=True)
        self.original = "prefix\n" + module.OLD + "\nsuffix\n"
        self.path.write_text(self.original)

    def test_apply_idempotent_and_revert(self):
        module.apply(self.root)
        self.assertIn(module.NEW, self.path.read_text())
        module.apply(self.root)
        module.apply(self.root, revert=True)
        module.apply(self.root, revert=True)
        self.assertEqual(self.path.read_text(), self.original)

    def test_unknown_source_does_not_change(self):
        self.path.write_text("unrelated source\n")
        with self.assertRaises(ValueError):
            module.apply(self.root)
        self.assertEqual(self.path.read_text(), "unrelated source\n")

    def test_shfl_pt_and_predicate_encoding(self):
        # The old translator uses B(w, 48, 3): PT=7 means no predicate write.
        self.assertIn("case O_SHFL: return B(w, 48, 3) != 7;", module.NEW)
        for predicate in range(8):
            word = predicate << 48
            self.assertEqual(((word >> 48) & 7) != 7, predicate != 7)

if __name__ == "__main__":
    unittest.main()
