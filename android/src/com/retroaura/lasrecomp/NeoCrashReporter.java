package com.retroaura.lasrecomp;

import android.content.Context;
import android.os.Build;
import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;

/**
 * Preserve Java crash evidence (including exceptions from the original
 * RadialGamePad's coroutine threads) in the existing diagnostics ZIP.
 * Does not suppress an exception or change the system's crash behavior.
 */
final class NeoCrashReporter {
    private static boolean installed;

    private NeoCrashReporter() {}

    static synchronized void install(Context context) {
        if (installed) return;
        final File output = new File(context.getApplicationContext().getFilesDir(),
                "neo_touch_crash.txt");
        final Thread.UncaughtExceptionHandler original =
                Thread.getDefaultUncaughtExceptionHandler();

        Thread.setDefaultUncaughtExceptionHandler((thread, failure) -> {
            try {
                StringWriter detail = new StringWriter();
                PrintWriter writer = new PrintWriter(detail);
                writer.println("time=" + System.currentTimeMillis());
                writer.println("device=" + Build.MANUFACTURER + "/" + Build.MODEL
                        + " sdk=" + Build.VERSION.SDK_INT);
                writer.println("thread=" + thread.getName());
                failure.printStackTrace(writer);
                writer.flush();
                try (FileOutputStream stream = new FileOutputStream(output, false)) {
                    stream.write(detail.toString().getBytes(StandardCharsets.UTF_8));
                    stream.getFD().sync();
                }
            } catch (Throwable ignored) {
                // Never hide the original exception or alter normal crash handling.
            } finally {
                if (original != null) {
                    original.uncaughtException(thread, failure);
                }
            }
        });
        installed = true;
    }
}
