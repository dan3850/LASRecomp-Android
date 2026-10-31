"""Source-level regression checks for optional conditional EXIT backport."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "conditional_exit", Path(__file__).resolve().parents[1] / "tools/patch_scarletnx_zelda_conditional_exit.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

class ConditionalExitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "src/nx/gpu/shader/spirv_translate.c"
        self.path.parent.mkdir(parents=True)
        self.original = "\n".join(old for old, _ in patch.PAIRS)
        self.path.write_text(self.original)

    def test_roundtrip(self):
        patch.apply(self.root)
        data = self.path.read_text()
        self.assertIn("!flow_always(insn[j])", data)
        self.assertIn("conditional_exit_seen", data)
        patch.apply(self.root)
        self.assertEqual(self.path.read_text(), data)
        patch.apply(self.root, revert=True)
        patch.apply(self.root, revert=True)
        self.assertEqual(self.path.read_text(), self.original)

    def test_partial_rejected(self):
        self.path.write_text(patch.NEW + patch.OLD_FLOW + patch.OLD_PRED)
        before = self.path.read_text()
        with self.assertRaises(ValueError):
            patch.apply(self.root)
        self.assertEqual(self.path.read_text(), before)

    def test_unrecognized_rejected(self):
        self.path.write_text("other translator")
        with self.assertRaises(ValueError):
            patch.apply(self.root)
        self.assertEqual(self.path.read_text(), "other translator")

    def test_conservative_predicated_definition(self):
        patch.apply(self.root)
        data = self.path.read_text()
        self.assertIn("(crossed || conditional_exit_seen || B(insn[j], 16, 4) != guard || pred_written)", data)
        self.assertIn("(op->id == O_EXIT && flow_always(insn[j]))", data)

if __name__ == "__main__":
    unittest.main()
