"""Composition-state diagnostics; GPU output remains a device observation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


PATCH=module('lighting_patch',ROOT/'tools/patch_scarletnx_zelda_lighting_diag.py')
HELPERS=module('lighting_helpers',ROOT/'tests/test_zelda_perf_uniform.py')


class LightingTests(unittest.TestCase):
    def test_transaction_idempotency_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original={}
            for name,pairs in PATCH.replacements().items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
                original[name]='\n/* anchor */\n'.join(old for old,new in pairs);p.write_text(original[name])
            PATCH.apply(root);once={n:(root/n).read_bytes() for n in original}
            PATCH.apply(root);self.assertEqual(once,{n:(root/n).read_bytes() for n in original})
            header=root/'src/nx/gpu/vk/snx_lighting_diag.h';good=header.read_bytes();header.write_text('unknown')
            with self.assertRaises(ValueError):PATCH.apply(root,True)
            self.assertEqual(once,{n:(root/n).read_bytes() for n in original})
            header.write_bytes(good);PATCH.apply(root,True);PATCH.apply(root,True)
            self.assertEqual(original,{n:(root/n).read_text() for n in original})
            (root/'src/nx/gpu/vk/renderer.c').write_text('unknown')
            with self.assertRaises(ValueError):PATCH.apply(root)
            self.assertFalse(header.exists())

    @unittest.skipUnless(shutil.which('cc'),'C compiler required')
    def test_real_observer_records_raw_and_effective_states_without_changing_inputs(self):
        gfx=(ROOT/'tools/zelda-perf/gfx_diag.h').read_text()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'gfx_first_actual.inc').write_text(HELPERS.function(gfx,'static int snx_gfx_first('))
            binary=root/'lighting'
            build=subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-I'+d,
                '-I'+str(ROOT/'tools/zelda-perf'),str(ROOT/'tests/zelda_lighting_diag_fixture.c'),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr+run.stdout)
            self.assertIn('LIGHTING_DIAG_OK off_no_work=1 inputs_immutable=1 separate_bounds=1',run.stdout)
            rows=[(s.split(' ',1)[0],json.loads(s.split(' ',1)[1])) for s in run.stdout.splitlines() if s.startswith('SNX_')]
            self.assertTrue(all(len(s.encode())<2048 for s in run.stdout.splitlines()))
            states=[v for k,v in rows if k=='SNX_LIGHT_STATE_V1'];textures=[v for k,v in rows if k=='SNX_LIGHT_RT_V1']
            self.assertEqual((len(states),len(textures)),(68,65))
            self.assertEqual(states[0]['regs']['4c7'],'ffffffff')
            self.assertEqual(states[1]['regs']['4c7'],'3f000000')
            self.assertNotEqual(states[1]['blend_effective'],states[2]['blend_effective'])
            self.assertEqual(states[3]['color_slot'],1)
            self.assertEqual(states[0]['viewport_depth_bits'],['bf800000','3f800000'])
            self.assertEqual(textures[0]['tic'],[0xffffffff]*8)
            self.assertEqual(textures[0]['handle'],'00000000')
            reports={v['window']:v for k,v in rows if k=='SNX_LIGHT_V1'}
            self.assertEqual(reports[1]['state_records'],4);self.assertEqual(reports[1]['color_rt_records'],1)
            self.assertTrue(all(v==0 for k,v in reports[2].items() if k!='window'))
            self.assertEqual(reports[3]['state_attempts'],200)
            self.assertEqual(reports[3]['state_limited'],1);self.assertEqual(reports[3]['color_rt_limited'],1)
            self.assertEqual(reports[3]['line_refused'],0)

    def test_signed_profile_keeps_depth_and_pool_markers(self):
        script=(ROOT/'compilar-zelda-iluminacao-termux.sh').read_text()
        gate=script.split("<<'PY'\n",1)[1].split('\nPY\n',1)[0]
        markers=('SNX_LIGHT_META_V1','SNX_LIGHT_STATE_V1','SNX_LIGHT_RT_V1','SNX_LIGHT_V1',
                 'SNX_DEPTH_RANGE_META_V1','SNX_VB_POOL_META_V1','revision')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.apk'
            for missing in ('','asset',*markers):
                with zipfile.ZipFile(p,'w') as z:
                    z.writestr('assets/licenses/Zelda-LightDiagnostics.txt','old' if missing=='asset' else 'revision')
                    z.writestr('lib/arm64-v8a/libscarletnx.so',' '.join(x for x in markers if x!=missing))
                run=subprocess.run([os.sys.executable,'-c',gate,str(p),'revision'],capture_output=True,text=True)
                self.assertEqual(run.returncode==0,missing=='',run.stderr)

    def test_analyzer_retains_limits_and_demands_complete_summary(self):
        analyzer=module('lighting_analyzer',ROOT/'tools/analyze_zelda_perf.py')
        rows=[('SNX_PERF_META_V1',{'revision':'lighting'})]
        for w in (1,2):
            rows.append(('SNX_PERF_V1',{'window':w,'elapsed_s':5*w,'duration_ms':5000}))
            for stream in ('guest_queue','render','present_enqueue'):
                rows.extend([('SNX_STREAM_V1',{'window':w,'stream':stream,'frames':2,'samples':1,'lost':0}),
                             ('SNX_FRAMES_V1',{'window':w,'stream':stream,'us':[16667]})])
            rows.extend(('SNX_COST_V1',{'window':w,'metric':str(n),'calls':0,'ms':0}) for n in range(16))
            rows.append(('SNX_VK_V1',{'window':w,'draws':2}))
        def log(rs):return '\n'.join(k+' '+json.dumps(v) for k,v in rs)
        baseline=analyzer.analyze(log(rows),0)
        meta=[('SNX_LIGHT_META_V1',{'diagnostic_only':1})]
        summaries=[('SNX_LIGHT_V1',{'window':w,'state_attempts':100,'state_records':64,'state_limited':1,
                   'color_rt_limited':0,'line_refused':0}) for w in (1,2)]
        result=analyzer.analyze(log(rows+meta+summaries),0)
        self.assertEqual(result['streams'],baseline['streams'])
        self.assertEqual(result['lighting_diagnostics']['state_limited_windows'],2)
        self.assertEqual(result['lighting_diagnostics']['state_attempts'],200)
        self.assertEqual(analyzer.analyze(log(rows+meta+summaries[:1]),0)['windows'],1)


if __name__=='__main__':unittest.main()
