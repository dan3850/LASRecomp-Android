"""Tests for the opt-in shader-window backport, without an Android build."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

PATCH = Path(__file__).resolve().parents[1] / "tools/patch_scarletnx_zelda_shader_window.py"
spec = importlib.util.spec_from_file_location("shader_window", PATCH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ShaderWindowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.file = self.root / "src/nx/gpu/vk/pipeline.c"
        self.file.parent.mkdir(parents=True)
        self.original = "\n".join([mod.OLD] + [old for old, _ in mod.TAIL])
        self.file.write_text(self.original)

    def test_roundtrip_and_idempotence(self):
        mod.apply(self.root)
        patched = self.file.read_text()
        self.assertIn("gva_a ? 0x10000u : 0x20000u", patched)
        self.assertIn("shader_corpus_save(vk_corpus_dir(), code, mlen, snx_shader_window", patched)
        mod.apply(self.root)
        self.assertEqual(self.file.read_text(), patched)
        mod.apply(self.root, revert=True)
        mod.apply(self.root, revert=True)
        self.assertEqual(self.file.read_text(), self.original)

    def test_partial_source_is_rejected_without_write(self):
        self.file.write_text(mod.NEW + "\n" + "\n".join(old for old, _ in mod.TAIL))
        before = self.file.read_text()
        with self.assertRaises(ValueError):
            mod.apply(self.root)
        self.assertEqual(self.file.read_text(), before)

    def test_unknown_source_is_rejected_without_write(self):
        self.file.write_text("unrelated pipeline")
        with self.assertRaises(ValueError):
            mod.apply(self.root)
        self.assertEqual(self.file.read_text(), "unrelated pipeline")

    def test_dual_vertex_merge_remains_bounded(self):
        mod.apply(self.root)
        text = self.file.read_text()
        self.assertIn("gva_a ? 0x10000u : 0x20000u", text)
        self.assertNotIn("shader_merge_dual(a, code, m, 0x20000)", text)

if __name__ == "__main__":
    unittest.main()
