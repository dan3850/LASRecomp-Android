#!/usr/bin/env python3
"""Synthetic tests for fail-closed ScarletNX Ryujinx pipeline patch."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "tools/patch_scarletnx_ryujinx_runtime.py"
spec = importlib.util.spec_from_file_location("snx_ryujinx_patch", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SYNTHETIC = (
    '#include "nx/gpu/vk/internal_spv.h"\n'
    'void vk_shader_get(void) {\n'
    + mod.CALL_OLD + '\n'
    + mod.MODULE_OLD + '\n'
    + '}\n'
)


class RuntimePatchTest(unittest.TestCase):
    def test_roundtrip_and_idempotence(self):
        patched = mod.transform(SYNTHETIC)
        self.assertIn(mod.INCLUDE_NEW, patched)
        self.assertIn(mod.CALL_NEW, patched)
        self.assertIn(mod.MODULE_NEW, patched)
        self.assertEqual(mod.transform(patched), patched)
        self.assertEqual(mod.transform(patched, revert=True), SYNTHETIC)
        self.assertEqual(mod.transform(SYNTHETIC, revert=True), SYNTHETIC)

    def test_refuses_partial_patch(self):
        with self.assertRaisesRegex(ValueError, "mixed"):
            mod.transform(SYNTHETIC.replace(mod.MODULE_OLD, "different source"))

    def test_native_fallback_and_private_opt_in(self):
        h = mod.HEADER
        self.assertIn('getenv("SNX_RYUJINX_BRIDGE")', h)
        self.assertIn("memcmp(code, e->code, code_len)", h)
        self.assertIn("stage != ST_FS", h)
        self.assertIn("si->tex[i]", h)
        self.assertIn("vk_translate_spirv", mod.CALL_NEW)
        self.assertIn("pf_shader_record(s, spv, nw)", mod.MODULE_OLD)
        self.assertIn("else if (!used_ryujinx_bridge)", mod.MODULE_NEW)


if __name__ == "__main__":
    unittest.main()
