"""Execute the shared Java exit reporter with retained Android history endpoints.

This checks the real adapter/export code, limits and binary trace preservation;
the phone's OS must still supply the actual exit reason after a process dies.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'android/src/com/retroaura/lasrecomp'


class ExitInfoTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('java'), 'host JDK required')
    def test_history_scope_binary_trace_bounds_state_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            files = {
                'android/os/Build.java': 'package android.os; public class Build {public static class VERSION {public static int SDK_INT=29;}}',
                'android/content/Context.java': '''package android.content; public class Context {
                    public static final String ACTIVITY_SERVICE="activity";
                    public java.io.File folder; public android.app.ActivityManager manager;
                    public Object getSystemService(String s){return manager;}
                    public java.io.File getFilesDir(){return folder;}
                    public String getPackageName(){return "test.zelda";}}''',
                'android/app/ActivityManager.java': '''package android.app; public class ActivityManager {
                    public java.util.List<ApplicationExitInfo> history;public String requested;public byte[] state;
                    public java.util.List<ApplicationExitInfo> getHistoricalProcessExitReasons(String p,int pid,int max){
                        if(pid!=0||max!=8)throw new AssertionError();requested=p;return history;}
                    public void setProcessStateSummary(byte[] s){state=s;}}''',
                'android/app/ApplicationExitInfo.java': '''package android.app; public class ApplicationExitInfo {
                    public static final int REASON_CRASH_NATIVE=5,REASON_ANR=6;
                    public String process,description;public int reason;public byte[] trace,summary;
                    public long getTimestamp(){return 1792875000000L;}public int getReason(){return reason;}
                    public int getStatus(){return 11;}public int getPid(){return 123;}public String getProcessName(){return process;}
                    public int getImportance(){return 100;}public long getPss(){return 1024;}public long getRss(){return 2048;}
                    public String getDescription(){return description;}public byte[] getProcessStateSummary(){return summary;}
                    public java.io.InputStream getTraceInputStream(){return trace==null?null:new java.io.ByteArrayInputStream(trace);}}''',
                'com/retroaura/lasrecomp/ExitHarness.java': '''package com.retroaura.lasrecomp;
                    import android.app.*;import android.content.Context;import android.os.Build;
                    import java.io.*;import java.nio.file.*;import java.nio.charset.StandardCharsets;import java.util.*;
                    public class ExitHarness {public static void main(String[] args)throws Exception {
                        Context c=new Context();c.folder=new File(args[0]);c.manager=new ActivityManager();
                        ScarletNxExitInfo.save(c);if(c.manager.requested!=null)throw new AssertionError("old Android called API");
                        Build.VERSION.SDK_INT=36;
                        ApplicationExitInfo normal=new ApplicationExitInfo();normal.process="test.zelda";normal.reason=1;
                        ApplicationExitInfo crash=new ApplicationExitInfo();crash.process="test.zelda:snx";crash.reason=5;
                        crash.description="native\\ncrash";crash.trace=new byte[70000];
                        for(int i=0;i<crash.trace.length;i++)crash.trace[i]=(byte)i;
                        crash.summary="Zelda D24-integration=2 requested=true".getBytes(StandardCharsets.UTF_8);
                        c.manager.history=Arrays.asList(normal,crash);ScarletNxExitInfo.save(c);
                        if(!"test.zelda".equals(c.manager.requested))throw new AssertionError("wrong UID scope");
                        String s=Files.readString(c.folder.toPath().resolve("mario-exit.log"));
                        if(!s.contains("exit[1]")||!s.contains("reason=5 status=11")||!s.contains("description=native crash")||
                           !s.contains("truncated=true")||!s.contains("requested=true"))throw new AssertionError(s);
                        String encoded=s.split("truncated=true\\n",2)[1].split("\\n",2)[0];
                        byte[] data=Base64.getDecoder().decode(encoded);
                        if(data.length!=49152||!Arrays.equals(data,Arrays.copyOf(crash.trace,49152)))throw new AssertionError("trace changed");
                        String report=ScarletNxLogReport.build(c.folder,"01006BB00C6F0000");
                        if(!report.contains("ANDROID_EXIT_INFO_V1")||!report.contains(encoded))throw new AssertionError("exit truncated in export");
                        ScarletNxExitInfo.state(c,"D24-integration=2");if(!new String(c.manager.state,StandardCharsets.UTF_8).equals("D24-integration=2"))throw new AssertionError();
                        byte[] before=c.manager.state;ScarletNxExitInfo.state(c,new String(new char[129]));if(before!=c.manager.state)throw new AssertionError("summary bound");
                        crash.trace=null;crash.reason=6;ScarletNxExitInfo.save(c);
                        s=Files.readString(c.folder.toPath().resolve("mario-exit.log"));if(!s.contains("did not retain a trace"))throw new AssertionError();
                        c.manager.history=Collections.emptyList();ScarletNxExitInfo.save(c);
                        s=Files.readString(c.folder.toPath().resolve("mario-exit.log"));if(!s.contains("Nenhum encerramento"))throw new AssertionError();
                        System.out.println("EXIT_INFO_OK own_package=1 binary_exact=1 bounded=1 nullable_trace=1 shared_export=1");
                    }}''',
            }
            for name, text in files.items():
                path = out / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            sources = [str(out / n) for n in files] + [str(JAVA / n) for n in ('ScarletNxExitInfo.java', 'ScarletNxLogReport.java')]
            run = subprocess.run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-d', d, *sources], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            run = subprocess.run(['java', '-cp', d, 'com.retroaura.lasrecomp.ExitHarness', d], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('EXIT_INFO_OK', run.stdout)


if __name__ == '__main__': unittest.main()
