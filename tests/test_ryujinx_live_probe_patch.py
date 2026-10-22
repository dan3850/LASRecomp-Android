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
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parents[1] / "tools/ryujinx-nativeaot/patch_scarletnx_live_probe.py"
SPEC = importlib.util.spec_from_file_location("ryujinx_live_probe_patch", SOURCE)
PATCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PATCH
SPEC.loader.exec_module(PATCH)


class LiveProbePatchTest(unittest.TestCase):
    def source(self):
        return (
            '#include "nx/gpu/vk/internal_spv.h"\n'
            "void pf_start_load(void) {\n"
            + PATCH.CACHE_OLD + "\n}\n"
            +             "void fake_fragment_pipeline(void) {\n"
            "        if (spv) {\n"
            "            VkShaderModuleCreateInfo mi = {\n"
            "                .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};\n"
            "        }\n"
            "}\n"
        )

    def test_patch_reverts_and_does_not_swap_gpu_shader(self):
        source = self.source()
        updated = PATCH.transform(source)
        self.assertIn("snx_rn_live_try_vulkan(code, mlen, stage, &candidate, &cnw);", updated)
        self.assertIn("if (!spv && stage == ST_FS)", updated)
        self.assertIn("s->si = candidate;", updated)
        self.assertIn("vk_spirv_unavailable(adapted, cnw)", updated)
        self.assertIn("persistent shader cache bypassed for this session", updated)
        self.assertIn("existing files untouched", updated)
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
            self.assertIn('dlsym(snx_rn_lib, "snx_ryu_translate_scarlet_v1")', header.read_text())
            self.assertIn("return NULL;", header.read_text())
            self.assertIn("snx_rn_live_try_vulkan", pipeline.read_text())
            PATCH.apply(root, revert=True)
            self.assertEqual(pipeline.read_text(), source)
            self.assertFalse(header.exists())

    def test_generated_c_compiles_standalone(self):
        compiler = shutil.which("cc")
        if not compiler:
            self.skipTest("C compiler unavailable")
        with tempfile.TemporaryDirectory() as d:
            header = Path(d) / "snx_ryujinx_native_live_probe.h"
            header.write_text(PATCH.HEADER)
            test = Path(d) / "probe.c"
            test.write_text(
                '#include <stdio.h>\n#include <stdint.h>\n'
                'typedef uint8_t u8; typedef uint32_t u32;\n'
                '#define ST_FS 4\n#define SH_MAXTEX 64\n'
                '#define WARN(...) fprintf(stderr, __VA_ARGS__)\n'
                'typedef struct {u8 type,bindless,bl_cbuf,bl2,bl2_cbuf;u32 cbuf_off,bl2_off;} ShTex;\n'
                'typedef struct {int stage;u32 sph[20],cbuf_mask,cbuf_max[18],in_mask,out_mask;'
                'int ntex,nimg,ngbuf,unsupported;char first_unsupported[96];ShTex tex[64];'
                'uint64_t tex_int_mask,tex_sint_mask,tex_dc_color_mask;'
                'u32 rt_int_mask,rt_sint_mask,tex_dc_color_funcs,in_unfed_mask,early_fragment_tests;} ShaderInfo;\n'
                '#include "snx_ryujinx_native_live_probe.h"\n'
                'u32* invoke_probe(const unsigned char* code, unsigned n,ShaderInfo* si,size_t* words) {'
                'return snx_rn_live_try_vulkan(code,n,ST_FS,si,words); }\n'
            )
            subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-c", str(test), "-o", str(Path(d) / "probe.o")],
                           check=True, capture_output=True, text=True)

    def test_probe_has_no_hardcoded_game_or_shader_key(self):
        self.assertNotIn(".snxrbr", PATCH.HEADER)
        self.assertNotIn("ace294a5", PATCH.HEADER)
        self.assertNotIn("214b89d4", PATCH.HEADER)
        self.assertIn('SNX_RYUJINX_NATIVE_PROBE', PATCH.HEADER)
        self.assertIn("snx_rn_adapt", PATCH.HEADER)
        self.assertIn("snx_rn_free(&out)", PATCH.HEADER)
        self.assertIn("snx_rn_attempts >= 256", PATCH.HEADER)


if __name__ == "__main__":
    unittest.main()
