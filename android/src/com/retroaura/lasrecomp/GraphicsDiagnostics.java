package com.retroaura.lasrecomp;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Only app-owned diagnostic evidence. Never enumerates/imports game folders. */
final class GraphicsDiagnostics {
    static final int SAVE_ZIP = 104;
    private static final int LOG_LIMIT = 1024 * 1024;
    static void chooseDestination(Activity activity) {
        Intent picker = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        picker.addCategory(Intent.CATEGORY_OPENABLE);
        picker.setType("application/zip");
        String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
        picker.putExtra(Intent.EXTRA_TITLE, "LASRecomp-grafico-" + stamp + ".zip");
        activity.startActivityForResult(picker, SAVE_ZIP);
    }
    static boolean handleResult(Activity activity, int request, int result, Intent data) {
        if (request != SAVE_ZIP) return false;
        if (result != Activity.RESULT_OK || data == null || data.getData() == null) return true;
        Uri target = data.getData();
        new Thread(() -> {
            String message;
            try (OutputStream raw = activity.getContentResolver().openOutputStream(target, "wt")) {
                if (raw == null) throw new java.io.IOException("Destino indisponível");
                try (ZipOutputStream zip = new ZipOutputStream(raw)) {
                    text(zip, "device-android.txt", "manufacturer=" + Build.MANUFACTURER + "\nmodel=" + Build.MODEL
                        + "\nAndroid=" + Build.VERSION.RELEASE + "\nSDK=" + Build.VERSION.SDK_INT
                        + "\npackage=" + activity.getPackageName() + "\n");
                    File root = activity.getFilesDir();
                    add(zip, new File(root, "lasrecomp_boot.txt"), "boot.txt", LOG_LIMIT, true);
                    add(zip, new File(root, "lasrecomp.log"), "runtime-tail.txt", LOG_LIMIT, true);
                    add(zip, new File(root, "lasrecomp.log"), "runtime-start.txt", 32768, false);
                    add(zip, new File(root, "mods/stable60-v2.status.txt"), "mods/status.txt", 4096, false);
                    String[] names = {"device.txt", "events.txt", "report.txt", "capture.state", "frame.png", "gl-overlay.txt"};
                    for (String name : names) add(zip, new File(root, "graphics/" + name), "graphics/" + name,
                        name.endsWith(".png") ? 32 * LOG_LIMIT : LOG_LIMIT, false);
                    for (int i = 0; i < 4; i++) for (String source : new String[] {"cpu", "gpu"}) {
                        String name = "atlas-" + i + "-" + source + ".png";
                        add(zip, new File(root, "graphics/" + name), "graphics/" + name, 32 * LOG_LIMIT, false);
                    }
                }
                message = "Diagnóstico gráfico salvo.";
            } catch (Exception error) { message = "Falha ao salvar diagnóstico: " + error.getMessage(); }
            final String outcome = message;
            activity.runOnUiThread(() -> Toast.makeText(activity, outcome, Toast.LENGTH_LONG).show());
        }, "LASRecompGraphicsExport").start();
        return true;
    }
    private static void text(ZipOutputStream zip, String name, String text) throws java.io.IOException {
        zip.putNextEntry(new ZipEntry(name)); zip.write(text.getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
    }
    private static void add(ZipOutputStream zip, File file, String name, int limit, boolean tail) throws java.io.IOException {
        if (!file.isFile()) return;
        long size = file.length();
        if (size > limit && !tail && !name.equals("runtime-start.txt")) throw new java.io.IOException("Diagnóstico excede o limite: " + name);
        try (FileInputStream in = new FileInputStream(file)) {
            if (tail && size > limit) in.getChannel().position(size - limit);
            zip.putNextEntry(new ZipEntry(name));
            byte[] buffer = new byte[16384];
            int remaining = limit;
            while (remaining > 0) {
                int n = in.read(buffer, 0, Math.min(buffer.length, remaining));
                if (n < 0) break;
                zip.write(buffer, 0, n); remaining -= n;
            }
            zip.closeEntry();
        }
    }
}
