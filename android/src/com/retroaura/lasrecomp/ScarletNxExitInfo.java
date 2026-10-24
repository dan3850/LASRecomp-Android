package com.retroaura.lasrecomp;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;

/** Shared retained-exit diagnostic, extracted from MarioBootActivity.
 * Read only this package's history, on export/return, never per frame.
 * A native tombstone can be protobuf: preserve bounded bytes as base64,
 * rather than inserting binary data into a UTF-8 text report. */
final class ScarletNxExitInfo {
    private ScarletNxExitInfo() { }

    private static String oneLine(String text) {
        if (text == null) return "null";
        return text.substring(0, Math.min(text.length(), 512)).replace('\r', ' ').replace('\n', ' ');
    }

    static void state(Context context, String text) {
        if (Build.VERSION.SDK_INT < 30) return;
        try {
            ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
            if (manager != null && bytes.length <= 128) manager.setProcessStateSummary(bytes);
        } catch (Exception ignored) { /* unavailable history must not block gameplay */ }
    }

    static synchronized void save(Context context) {
        if (Build.VERSION.SDK_INT < 30) return;
        File pending = new File(context.getFilesDir(), "mario-exit.pending");
        try {
            ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (manager == null) return;
            List<ApplicationExitInfo> history = manager.getHistoricalProcessExitReasons(context.getPackageName(), 0, 8);
            try (FileOutputStream output = new FileOutputStream(pending, false)) {
                StringBuilder report = new StringBuilder("ANDROID_EXIT_INFO_V1 collected_ms=" + System.currentTimeMillis() + "\n");
                if (history.isEmpty()) report.append("Nenhum encerramento anterior registrado pelo Android.\n");
                boolean capturedSnxCrash = false;
                for (int i = 0; i < Math.min(history.size(), 8); i++) {
                    ApplicationExitInfo info = history.get(i);
                    report.append("exit[").append(i).append("] timestamp=").append(info.getTimestamp())
                            .append(" reason=").append(info.getReason()).append(" status=").append(info.getStatus())
                            .append(" pid=").append(info.getPid()).append(" process=").append(oneLine(info.getProcessName()))
                            .append(" importance=").append(info.getImportance()).append(" pss_kb=").append(info.getPss())
                            .append(" rss_kb=").append(info.getRss()).append(" description=").append(oneLine(info.getDescription())).append('\n');
                    byte[] summary = info.getProcessStateSummary();
                    if (summary != null) report.append("process_state=").append(oneLine(new String(summary, 0,
                            Math.min(summary.length, 128), StandardCharsets.UTF_8))).append('\n');
                    boolean nativeCrash = info.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE;
                    boolean anr = info.getReason() == ApplicationExitInfo.REASON_ANR;
                    if (capturedSnxCrash || !(context.getPackageName() + ":snx").equals(info.getProcessName()) ||
                            (!nativeCrash && !anr)) continue;
                    capturedSnxCrash = true;
                    try (InputStream trace = info.getTraceInputStream()) {
                        if (trace == null) { report.append("Android did not retain a trace for this exit.\n"); continue; }
                        ByteArrayOutputStream data = new ByteArrayOutputStream();
                        byte[] chunk = new byte[4096];int n;
                        while (data.size() < 49152 && (n = trace.read(chunk, 0, Math.min(chunk.length, 49152 - data.size()))) > 0)
                            data.write(chunk, 0, n);
                        boolean truncated = data.size() == 49152 && trace.read() != -1;
                        report.append("android_trace exit_index=").append(i).append(" encoding=base64 bytes=")
                                .append(data.size()).append(" truncated=").append(truncated).append('\n')
                                .append(Base64.getEncoder().encodeToString(data.toByteArray())).append('\n');
                    } catch (Exception error) { report.append("Android trace unavailable: ").append(oneLine(error.toString())).append('\n'); }
                }
                output.write(report.toString().getBytes(StandardCharsets.UTF_8));
            }
            // Exporters can read concurrently: publish a complete report at once.
            if (!pending.renameTo(new File(context.getFilesDir(), "mario-exit.log"))) pending.delete();
        } catch (Exception ignored) { pending.delete(); /* unavailable history must not block log export */ }
    }
}
