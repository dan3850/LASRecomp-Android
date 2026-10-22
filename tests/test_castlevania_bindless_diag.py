#!/usr/bin/env python3
"""Pinned ScarletNX shader diagnostic patch tests: no behavior changes."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bindless_diag", ROOT / "tools/patch_scarletnx_bindless_diag.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

class TestBindlessDiagnostics(unittest.TestCase):
    def test_exact_six_sites_and_reversibility(self):
        original = ("start\n" + MODULE.OLD + "\n") * 6
        patched = MODULE.transform(original)
        self.assertEqual(patched.count(MODULE.NEW), 6)
        self.assertEqual(MODULE.transform(patched), patched)
        self.assertEqual(MODULE.transform(patched, revert=True), original)
        self.assertEqual(MODULE.transform(original, revert=True), original)

    def test_refuses_unknown_or_partial_sources(self):
        with self.assertRaises(ValueError):
            MODULE.transform("unknown")
        with self.assertRaises(ValueError):
            MODULE.transform(MODULE.OLD * 5 + MODULE.NEW)

    def test_reports_txq_and_txd_a_register(self):
        self.assertIn("O_TXD_B || op->id == O_TXQ_B", MODULE.NEW)
        self.assertIn("direct_reaching_def(insn, n, i, handle_reg)", MODULE.NEW)
        self.assertIn("return direct_reject(si, detail)", MODULE.NEW)

if __name__ == "__main__":
    unittest.main(verbosity=2)
