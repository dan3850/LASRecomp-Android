package com.retroaura.lasrecomp;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.util.HashSet;
import java.util.Set;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipEntry;

public final class ShadowCaptureExportFixture {
    private static void check(boolean condition) { if (!condition) throw new AssertionError(); }
    private static void refuses(File root) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try { ShadowCaptureExport.write(root, bytes, "log"); throw new AssertionError("accepted incomplete session"); }
        catch (IOException expected) { check(bytes.size() == 0); }
    }
    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        refuses(root);
        File old = new File(root, "0000000000000001"); check(old.mkdirs());
        Files.write(new File(old, "shadow-1.json").toPath(), "{}".getBytes("UTF-8"));
        Files.write(new File(old, "shadow-1.depth").toPath(), new byte[]{1, 2, 3, 4});
        File latest = new File(root, "0000000000000002"); check(latest.mkdir());
        refuses(root); // no fallback to an older successful capture
        Files.write(new File(latest, "shadow-1.depth").toPath(), new byte[]{1, 2, 3, 4});
        Files.write(new File(latest, "shadow-1.json.partial").toPath(), "{}".getBytes("UTF-8"));
        refuses(root); // metadata commit marker still missing
        Files.write(new File(latest, "shadow-1.json").toPath(), "{}".getBytes("UTF-8"));
        Files.write(new File(latest, "prod.keys").toPath(), "unrelated private file".getBytes("UTF-8"));
        Files.write(new File(latest, "shadow-4.json").toPath(), "out of bound".getBytes("UTF-8"));
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        check(ShadowCaptureExport.write(root, bytes, "test log") == 1);
        Set<String> names = new HashSet<>();
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
            ZipEntry entry; byte[] buffer = new byte[32];
            while ((entry = zip.getNextEntry()) != null) {
                names.add(entry.getName());
                ByteArrayOutputStream content = new ByteArrayOutputStream(); int n;
                while ((n = zip.read(buffer)) != -1) content.write(buffer, 0, n);
                if (entry.getName().endsWith(".depth"))
                    check(java.util.Arrays.equals(content.toByteArray(), new byte[]{1, 2, 3, 4}));
            }
        }
        check(names.size() == 3 && names.contains("Zelda-SNX-boot.txt") &&
              names.contains("shadows/0000000000000002/shadow-1.depth") &&
              names.contains("shadows/0000000000000002/shadow-1.json"));
        try (RandomAccessFile large = new RandomAccessFile(new File(latest, "shadow-1.depth"), "rw")) {
            large.setLength(64L * 1024 * 1024 + 1);
        }
        refuses(root);
        System.out.println("SHADOW_EXPORT_OK latest_only=1 complete_pairs=1 bounded=1 bytes_preserved=1");
    }
}
