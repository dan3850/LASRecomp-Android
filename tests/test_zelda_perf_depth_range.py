"""Actual viewport mapping and extension gating; no captured game fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get('SCARLETNX_TEST_SRC', ROOT.parent / 'ScarletNX-audit'))
PIN = '34853eeae5af132e320adbb0193f13344085bf89'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


PATCH = module('depth_patch', ROOT / 'tools/patch_scarletnx_zelda_depth_range.py')
HELPERS = module('depth_helpers', ROOT / 'tests/test_zelda_perf_uniform.py')


def patched(text, pairs):
    for old, new in pairs:
        if text.count(old) != 1:
            raise AssertionError('Unknown source: ' + old[:80])
        text = text.replace(old, new, 1)
    return text


class DepthRangeTests(unittest.TestCase):
    def test_transaction_idempotency_and_exact_rollback_preserve_shader_and_cache_sources(self):
        self.assertEqual(set(PATCH.replacements()), {'src/nx/gpu/vk/' + n for n in ('vk.h','device.c','render.c','renderer.c')})
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = {}
            for name, pairs in PATCH.replacements().items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True)
                original[name] = '\n/* anchor */\n'.join(old for old,new in pairs); p.write_text(original[name])
            PATCH.apply(root); once = {n:(root/n).read_bytes() for n in original}
            PATCH.apply(root); self.assertEqual(once,{n:(root/n).read_bytes() for n in original})
            header = root / 'src/nx/gpu/vk/snx_depth_range.h'; good = header.read_bytes()
            header.write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root,True)
            self.assertEqual(once,{n:(root/n).read_bytes() for n in original})
            header.write_bytes(good); PATCH.apply(root,True); PATCH.apply(root,True)
            self.assertEqual(original,{n:(root/n).read_text() for n in original})
            (root/'src/nx/gpu/vk/renderer.c').write_text('unknown')
            with self.assertRaises(ValueError): PATCH.apply(root)
            self.assertFalse(header.exists())
            self.assertEqual((root/'src/nx/gpu/vk/device.c').read_text(),original['src/nx/gpu/vk/device.c'])

    @unittest.skipUnless((SRC/'.git').exists() and shutil.which('cc'),'pinned source and C compiler required')
    def test_real_device_selection_and_viewport_fix_captured_mapping_with_off_exact(self):
        before = subprocess.check_output(['git','-C',str(SRC),'show',PIN+':src/nx/gpu/vk/render.c'],text=True)
        after = patched(before,PATCH.replacements()['src/nx/gpu/vk/render.c'])
        device = subprocess.check_output(['git','-C',str(SRC),'show',PIN+':src/nx/gpu/vk/device.c'],text=True)
        device = patched(device,PATCH.replacements()['src/nx/gpu/vk/device.c'])
        gate = device[device.index('    const char** ext = g_vk.dev_ext;'):device.index('    g_vk.video_family =')]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'depth_gate_actual.inc').write_text('static void gate_actual(void) {\n'+gate+'\n g_vk.dev_ext_n=next;\n}\n')
            for label,text in (('before',before),('after',after)):
                (root/f'depth_{label}_actual.inc').write_text(HELPERS.function(text,'VkViewport vk_render_viewport(').replace('vk_render_viewport(',label+'_actual(',1))
            command = ['cc','-std=gnu11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-but-set-variable',
                       '-I'+d,'-I'+str(ROOT/'tools/zelda-perf'),str(ROOT/'tests/zelda_depth_range_fixture.c'),'-o',str(root/'depth')]
            build = subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run = subprocess.run([str(root/'depth')],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr+run.stdout)
            self.assertIn('DEPTH_RANGE_OK vectors=160 off_exact=1 extension_gated=1 mapping_preserved=1',run.stdout)
            self.assertEqual(run.stdout.count('SNX_DEPTH_RANGE_STATE_V1'),4)

    def test_signed_asset_and_runtime_gate_and_zelda_only_launch_option(self):
        gate=(ROOT/'compilar-zelda-profundidade-termux.sh').read_text().split("<<'PY'\n",1)[1].split('\nPY\n',1)[0]
        markers=('SNX_DEPTH_RANGE_META_V1','SNX_DEPTH_RANGE_STATE_V1','SNX_DEPTH_RANGE_V1',
                 'VK_EXT_depth_range_unrestricted','SNX_VB_POOL_META_V1','revision')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.apk'
            for missing in ('','asset',*markers):
                with zipfile.ZipFile(p,'w') as z:
                    z.writestr('assets/licenses/Zelda-DepthRange.txt','old' if missing=='asset' else 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so',' '.join(x for x in markers if x!=missing))
                run=subprocess.run([os.sys.executable,'-c',gate,str(p),'revision'],capture_output=True,text=True)
                self.assertEqual(run.returncode==0,missing=='',run.stderr)
        boot=(ROOT/'android/src/com/retroaura/lasrecomp/CastlevaniaSnxBootActivity.java').read_text()
        game=(ROOT/'android/src/com/retroaura/lasrecomp/MarioSnxGameActivity.java').read_text()
        self.assertIn('getBoolean("zelda_depth_range_v1", hasDepthRangeBuild())',boot)
        self.assertIn('zelda && getIntent().getBooleanExtra("snx_depth_range", false)',game)

    def test_analyzer_reports_device_capability_and_requires_complete_consistent_windows(self):
        analyzer=module('depth_analyzer',ROOT/'tools/analyze_zelda_perf.py')
        rows=[('SNX_PERF_META_V1',{'revision':'depth'})]
        for w in (1,2):
            rows.append(('SNX_PERF_V1',{'window':w,'elapsed_s':5*w,'duration_ms':5000}))
            for stream in ('guest_queue','render','present_enqueue'):
                rows.extend([('SNX_STREAM_V1',{'window':w,'stream':stream,'frames':2,'samples':1,'lost':0}),
                             ('SNX_FRAMES_V1',{'window':w,'stream':stream,'us':[16667]})])
            rows.extend(('SNX_COST_V1',{'window':w,'metric':str(n),'calls':0,'ms':0}) for n in range(16))
            rows.append(('SNX_VK_V1',{'window':w,'draws':2}))
        def log(rs): return '\n'.join(k+' '+json.dumps(v) for k,v in rs)
        baseline=analyzer.analyze(log(rows),0)
        meta=[('SNX_DEPTH_RANGE_META_V1',{'requested':1,'supported':1,'enabled':1,'shader_changed':0})]
        counts=[('SNX_DEPTH_RANGE_V1',{'window':w,'enabled':1,'viewport_setups':2,'unrestricted_setups':1}) for w in (1,2)]
        report=analyzer.analyze(log(rows+meta+counts),0)
        self.assertEqual(report['streams'],baseline['streams'])
        self.assertEqual(report['depth_range']['unrestricted_setups'],2)
        self.assertEqual(report['metadata']['depth_range']['supported'],1)
        self.assertEqual(analyzer.analyze(log(rows+meta+counts[:1]),0)['windows'],1)
        with self.assertRaisesRegex(ValueError,'mode changed'):
            analyzer.analyze(log(rows+meta+[counts[0],(counts[1][0],{**counts[1][1],'enabled':0})]),0)


if __name__ == '__main__': unittest.main()
