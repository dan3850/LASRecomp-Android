#!/usr/bin/env python3
"""Verify reversible FSWZADD 0xD7 source patch and quad mask semantics."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/patch_scarletnx_fswzadd.py"
spec = importlib.util.spec_from_file_location("scarlet_shader_patch", MODULE)
patch = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(patch)

class TestCastlevaniaShaderPatch(unittest.TestCase):
    def test_exact_patterns_apply_and_revert(self):
        original = "\n--section--\n".join(a for a, _ in patch.REPLACES)
        changed = patch.apply(original)
        self.assertNotEqual(changed, original)
        self.assertIn("quad == 0xd7", changed)
        self.assertIn("c->subgroup_lane_input", changed)
        self.assertEqual(patch.apply(changed), changed)
        self.assertEqual(patch.apply(changed, revert=True), original)
        self.assertEqual(patch.apply(original, revert=True), original)

    def test_refuses_partial_patch(self):
        original = "\n--section--\n".join(a for a, _ in patch.REPLACES)
        changed = patch.apply(original)
        mixed = changed.replace(patch.REPLACES[1][1], patch.REPLACES[1][0])
        with self.assertRaises(ValueError):
            patch.apply(mixed)
        with self.assertRaises(ValueError):
            patch.apply("unknown upstream file")

    def test_d7_reference_lut(self):
        mask = 0xD7
        self.assertEqual([(mask >> (lane * 2)) & 3 for lane in range(4)],
                         [3, 1, 1, 3])
        x, y = 4.25, 7.5
        x_lut, y_lut = (1., -1., 1., 0.), (1., 1., -1., 1.)
        expected = [x * x_lut[(mask >> (lane * 2)) & 3] +
                    y * y_lut[(mask >> (lane * 2)) & 3]
                    for lane in range(4)]
        experimental = [y - x if lane in (1, 2) else y
                        for lane in range(4)]
        self.assertEqual(experimental, expected)

if __name__ == "__main__":
    unittest.main(verbosity=2)
