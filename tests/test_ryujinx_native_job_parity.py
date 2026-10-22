#!/usr/bin/env python3
"""Prevent live and standalone Ryujinx shader context/options from diverging.

The first actual in-game test failed 5/5 shaders after the live C caller used
"debug":false, while the direct Termux test had DebugMode ON. Compare the
complete JSON sent by the C caller with the known-good Python caller, not just
the one property. This test does not need a GPU or Nintendo shader assets.
"""
import ast
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "tools/ryujinx-nativeaot"
for directory in (ROOT / "tools", NATIVE):
    sys.path.insert(0, str(directory))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PATCH = load("ryujinx_live_options", NATIVE / "patch_scarletnx_live_probe.py")
TEST = load("ryujinx_direct_options", NATIVE / "test_native.py")


def c_live_job_json():
    source = PATCH.HEADER.split("static const char job[] =", 1)
    if len(source) != 2:
        raise ValueError("the ScarletNX live job declaration is absent")
    declaration = source[1].split(";", 1)[0]
    tokens = re.findall(r'"(?:\\.|[^"\\])*"', declaration)
    if not tokens:
        raise ValueError("the ScarletNX live job has no literal JSON strings")
    return "".join(ast.literal_eval(s) for s in tokens)


class RuntimeJobParityTests(unittest.TestCase):
    def test_exact_live_context_equals_known_good_arm64_test(self):
        job = json.loads(c_live_job_json())
        self.assertEqual(job, TEST.make_job("ps"))
        self.assertTrue(job["debug"])
        self.assertEqual(job["stage"], "ps")
        self.assertEqual(job["local"], [1, 1, 1])
        self.assertEqual(job["tex"], {})
        self.assertEqual(job["img"], {})
        self.assertEqual(job["fout"], {})
        self.assertEqual(job["attr"], {})

    def test_live_and_standalone_json_payloads_equal_byte_for_byte(self):
        standalone = json.dumps(TEST.make_job("ps"), separators=(",", ":"))
        self.assertEqual(c_live_job_json(), standalone)

    def test_debug_mode_changes_translate_flag_and_must_be_explict(self):
        bridge = (NATIVE / "BridgeExports.cs").read_text()
        self.assertIn('job["debug"] is JsonNode d && !d.GetValue<bool>()', bridge)
        self.assertIn('TranslationFlags.DebugMode', bridge)
        self.assertIs(TEST.make_job("ps")["debug"], True)
        self.assertNotIn('"debug":false', c_live_job_json())


if __name__ == "__main__":
    unittest.main()
