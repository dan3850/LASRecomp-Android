"""Fresh-source provenance and real C callback regressions. Native compilation is CI-only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/'tools/ryujinx-nativeaot'
spec = importlib.util.spec_from_file_location('prepare_v2', HERE/'prepare_source.py')
prepare = importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

class V2Tests(unittest.TestCase):
    def test_source_identity_changes_with_real_adapter_source(self):
        upstream = Path(os.environ.get('NX', ROOT.parent/'nxnative'))
        if not (upstream/'dm/gfx/tools/dmsh_xlate/Program.cs').exists(): self.skipTest('pinned source not present')
        original = (upstream/'dm/gfx/tools/dmsh_xlate/Program.cs').read_bytes()
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);source=folder/'src';shutil.copytree(HERE,source)
            out=folder/'stage';prepare.prepare(upstream,source,out)
            first=json.loads((out/'build-identity.json').read_text())
            prepare.prepare(upstream,source,out)
            self.assertEqual(json.loads((out/'build-identity.json').read_text()),first)
            adapter=source/'ScarletAdapterV2.cs';adapter.write_bytes(adapter.read_bytes()+b'\n// provenance mutation\n')
            prepare.prepare(upstream,source,out)
            self.assertNotEqual(json.loads((out/'build-identity.json').read_text()),first)
            self.assertEqual((upstream/'dm/gfx/tools/dmsh_xlate/Program.cs').read_bytes(),original)
            self.assertIn('RuntimeConstant', (out/'Program.Native.cs').read_text())
    @unittest.skipUnless(os.environ.get('SCARLETNX_CI_COMPILE')=='1','native compilation happens only in GitHub Actions')
    def test_real_runtime_callbacks_and_support_buffer(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);header=out/'nx/gpu/vk/snx_ryu_expected.h';header.parent.mkdir(parents=True)
            header.write_text('#define SNX_RYU_EXPECTED_IDENTITY "synthetic-test"\n#define SNX_RUNTIME_REVISION "ci-test"\n')
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Wno-unused-function','-I'+str(out),'-I'+str(HERE),
                str(HERE/'RuntimeV2Regression.c'),'-ldl','-o',str(out/'regression')],check=True)
            subprocess.run([str(out/'regression')],check=True)

if __name__=='__main__': unittest.main()
