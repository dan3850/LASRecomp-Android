#!/usr/bin/env python3
"""Source-only tests for the Zelda Stable60 opt-in patch. No game files needed."""
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = runpy.run_path(str(ROOT / "tools/patch_scarletnx_zelda60_toggle.py"))
PATCH = MOD["patch"]
REPL = MOD["REPLACEMENTS"]


class Zelda60TogglePatchTest(unittest.TestCase):
    def tree(self, root: Path):
        original = {}
        for path in sorted({x["path"] for x in REPL}):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = "\n".join(x["old"] for x in REPL if x["path"] == path)
            target.write_text(content, encoding="utf-8")
            original[path] = content
        return original

    def test_apply_idempotent_and_revert(self):
        for mode in ("aot", "runtime", "all"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original = self.tree(root)
                PATCH(root, mode, check=True)
                self.assertEqual(original, {p: (root / p).read_text() for p in original})
                PATCH(root, mode)
                once = {p: (root / p).read_text() for p in original}
                PATCH(root, mode)
                self.assertEqual(once, {p: (root / p).read_text() for p in original})
                PATCH(root, mode, revert=True)
                self.assertEqual(original, {p: (root / p).read_text() for p in original})

    def test_unknown_source_fails_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.tree(root)
            target = root / REPL[0]["path"]
            target.write_text("unknown revision", encoding="utf-8")
            with self.assertRaises(ValueError):
                PATCH(root, "all")
            for path, content in original.items():
                self.assertEqual(
                    "unknown revision" if path == REPL[0]["path"] else content,
                    (root / path).read_text(),
                )


if __name__ == "__main__":
    unittest.main()
