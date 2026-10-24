package com.retroaura.lasrecomp;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Only complete depth/metadata pairs from the newest capture session. */
final class ShadowCaptureExport {
    private ShadowCaptureExport() { }

    static int write(File captures, OutputStream output, String log) throws IOException {
        File[] sessions = captures.listFiles((dir, name) -> name.matches("[0-9a-f]{16}"));
        if (sessions == null || sessions.length == 0)
            throw new IOException("Ative Capturar sombras, inicie o jogo e fique na cena por 60 segundos.");
        Arrays.sort(sessions, (a, b) -> b.getName().compareTo(a.getName()));
        File session = sessions[0];
        File[] metadata = session.listFiles((dir, name) -> name.matches("shadow-[1-3]\\.json"));
        if (metadata == null || metadata.length == 0)
            throw new IOException("A ultima sessao ainda nao tem amostras completas. Aguarde na cena e saia pelo menu.");
        Arrays.sort(metadata, (a, b) -> a.getName().compareTo(b.getName()));
        // Validate everything before writing the archive; never silently mix an
        // older successful session into the current failed/incomplete attempt.
        for (File meta : metadata) {
            File depth = new File(session, meta.getName().replace(".json", ".depth"));
            if (!meta.isFile() || meta.length() == 0 || meta.length() > 16384 ||
                    !depth.isFile() || depth.length() == 0 || depth.length() > 64L * 1024 * 1024)
                throw new IOException("Amostra incompleta ou excede o limite: " + meta.getName());
        }
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            byte[] buffer = new byte[32768];
            for (File meta : metadata) {
                for (String extension : new String[]{".json", ".depth"}) {
                    File file = new File(session, meta.getName().replace(".json", extension));
                    zip.putNextEntry(new ZipEntry("shadows/" + session.getName() + "/" + file.getName()));
                    long remaining = extension.equals(".json") ? 16384 : 64L * 1024 * 1024;
                    try (FileInputStream in = new FileInputStream(file)) {
                        int n;
                        while ((n = in.read(buffer)) != -1) {
                            remaining -= n;
                            if (remaining < 0) throw new IOException("Amostra cresceu durante a exportacao");
                            zip.write(buffer, 0, n);
                        }
                    }
                    zip.closeEntry();
                }
            }
            zip.putNextEntry(new ZipEntry("Zelda-SNX-boot.txt"));
            zip.write(log.getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
        }
        return metadata.length;
    }
}
