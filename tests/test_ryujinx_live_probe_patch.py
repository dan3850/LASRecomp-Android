#!/usr/bin/env python3
"""Opt-in LIVE Ryujinx NativeAOT build for Castlevania (SHADOW MODE ONLY).

The real Ryujinx translator executes *inside ScarletNX's game process* for
new Maxwell fragments rejected by ScarletNX; it does not yet supply their
SPIR-V to the GPU. This separates load/translation correctness from descriptor
layout adaptation, and never uses .snxrbr files or per-game shader lists.
"""
import unittest
from pathlib import Path
import importlib.util
import tempfile
import sys

SOURCE = Path(__file__).resolve().parents[1] / "tools/ryujinx-nativeaot/patch_scarletnx_live_probe.py"
SPEC = importlib.util.spec_from_file_location("ryujinx_live_probe_patch", SOURCE)
PATCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PATCH
SPEC.loader.exec_module(PATCH)


class LiveProbePatchTest(unittest.TestCase):
    def source(self):
        return (
            '#include "nx/gpu/vk/internal_spv.h"\n'
            "void fake_fragment_pipeline(void) {\n"
            "        if (spv) {\n"
            "            VkShaderModuleCreateInfo mi = {\n"
            "                .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};\n"
            "        }\n"
            "}\n"
        )

    def test_patch_reverts_and_does_not_swap_gpu_shader(self):
        source = self.source()
        updated = PATCH.transform(source)
        self.assertIn("snx_rn_live_probe(code, mlen, stage);", updated)
        self.assertIn("if (!spv && stage == ST_FS)", updated)
        self.assertIn("if (spv) {", updated)
        self.assertEqual(PATCH.transform(updated), updated)
        self.assertEqual(PATCH.transform(updated, revert=True), source)
        self.assertEqual(PATCH.transform(source, revert=True), source)

    def test_guard_rejects_unknown_pipeline_source(self):
        with self.assertRaisesRegex(ValueError, "pipeline changed"):
            PATCH.transform('#include "nx/gpu/vk/internal_spv.h"\n')
        with self.assertRaisesRegex(ValueError, "pipeline changed"):
            PATCH.transform(self.source().replace("        if (spv) {", "        if (newspv) {"))

    def test_generated_header_checked_and_source_restored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pipeline = root / "src/nx/gpu/vk/pipeline.c"
            pipeline.parent.mkdir(parents=True)
            source = self.source()
            pipeline.write_text(source)
            PATCH.apply(root)
            header = pipeline.parent / "snx_ryujinx_native_live_probe.h"
            self.assertTrue(header.is_file())
            self.assertIn('dlsym(snx_rn_lib, "snx_ryu_translate_v1")', header.read_text())
            self.assertIn("original ScarletNX failure retained", header.read_text())
            self.assertIn("snx_rn_live_probe", pipeline.read_text())
            PATCH.apply(root, revert=True)
            self.assertEqual(pipeline.read_text(), source)
            self.assertFalse(header.exists())

    def test_probe_has_no_hardcoded_game_or_shader_key(self):
        self.assertNotIn(".snxrbr", PATCH.HEADER)
        self.assertNotIn("ace294a5", PATCH.HEADER)
        self.assertNotIn("214b89d4", PATCH.HEADER)
        self.assertIn('SNX_RYUJINX_NATIVE_PROBE', PATCH.HEADER)
        self.assertIn("snx_rn_translate", PATCH.HEADER)
        self.assertIn("snx_rn_free(&out)", PATCH.HEADER)
        self.assertIn("snx_rn_attempts >= 32", PATCH.HEADER)


if __name__ == "__main__":
    unittest.main()
