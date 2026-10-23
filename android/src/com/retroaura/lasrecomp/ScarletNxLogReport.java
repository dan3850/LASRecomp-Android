package com.retroaura.lasrecomp;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Locale;

/**
 * Keeps relevant shader failures in an exported diagnostic even when the
 * ScarletNX .log is gigabytes long. The old exporter kept only the final 60 KB
 * and discarded the first Vulkan shader rejection lines.
 */
final class ScarletNxLogReport {
    private static final int START_BYTES = 8192;
    private static final int TAIL_BYTES = 14000;
    private static final int MAX_SHADER_LINES = 150;
    private static final int MAX_RYU_LINES = 100;
    private static final int MAX_STATS_LINES = 90;
    private static final int MAX_PERF_BYTES = 8 * 1024 * 1024;

    private ScarletNxLogReport() { }

    private static void window(StringBuilder out, File file, int limit, boolean tail) {
        try (RandomAccessFile raf = new RandomAccessFile(file, "r")) {
            long length = raf.length();
            int count = (int)Math.min(length, limit);
            long start = tail ? length - count : 0;
            raf.seek(start);
            byte[] data = new byte[count];
            raf.readFully(data);
            out.append(tail ? "\n=== FINAL DO LOG ===\n" : "\n=== INICIO DO LOG ===\n");
            if (start > 0) out.append("[Trecho inicial omitido nesta janela]\n");
            out.append(new String(data, StandardCharsets.UTF_8));
            if (!tail && count < length) out.append("\n[Omitido ate o trecho final]\n");
        } catch (Exception error) {
            out.append("Erro lendo trecho: ").append(error).append('\n');
        }
    }

    static String build(File appFiles, String gameId) {
        StringBuilder out = new StringBuilder(125000);
        out.append("Castlevania ScarletNX — diagnostico de renderizacao\n");
        out.append("Resumo: linhas de shader extraidas de TODO o log, ");
        out.append("com inicio/fim preservados e limites de memoria.\n");
        for (String name : new String[]{"mario-snx-launch.log", "mario-snx-native.log"}) {
            File file = new File(appFiles, name);
            if (!file.isFile()) continue;
            out.append("\n=== ").append(name).append(" ===\n");
            window(out, file, 8000, true);
        }

        File state = new File(new File(new File(appFiles, "snx-games"), gameId), "state");
        File[] logs = state.listFiles((dir, name) -> name.endsWith(".log"));
        if (logs == null || logs.length == 0) {
            out.append("\nNenhum log do runtime ScarletNX localizado.\n");
            return out.toString();
        }
        Arrays.sort(logs, (a, b) -> Long.compare(b.lastModified(), a.lastModified()));
        // Analyze the newest game log. Previous attempts are retained on disk.
        File log = logs[0];
        out.append("\n=== ScarletNX ").append(log.getName()).append(" ===\n");
        out.append("Tamanho original: ").append(log.length()).append(" bytes\n");
        window(out, log, START_BYTES, false);

        StringBuilder shaders = new StringBuilder();
        StringBuilder nativeRyujinx = new StringBuilder();
        StringBuilder stats = new StringBuilder();
        StringBuilder perf = new StringBuilder();
        boolean perfTruncated = false;
        int shaderWarnings = 0, fswzadd = 0, untracked = 0, statsCount = 0, ryujinxCount = 0;
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(new FileInputStream(log), StandardCharsets.UTF_8), 65536)) {
            String line;
            while ((line = reader.readLine()) != null) {
                // Keep complete telemetry exactly once. Start/end preview
                // windows may contain copies of these same lines.
                if ((line.contains("SNX_") && line.contains("_V1 "))
                        || line.contains("vulkan: GPU ") || line.contains("vulkan: buffer ")
                        || line.contains("write tracking") || line.contains("memory: no traps")
                        || line.contains("memory: GPU engines keep")) {
                    if (perf.length() + line.length() + 1 <= MAX_PERF_BYTES) perf.append(line).append('\n');
                    else perfTruncated = true;
                }
                String low = line.toLowerCase(Locale.ROOT);
                boolean warning = low.contains("not translated") ||
                    low.contains("unsupported") || low.contains("failed") ||
                    low.contains("error") || low.contains("could not") ||
                    low.contains("fatal");
                if (low.contains("fswzadd")) fswzadd++;
                if (low.contains("untracked texture handle")) untracked++;
                if (low.contains("ryujinx_native_")) {
                    ryujinxCount++;
                    if (ryujinxCount <= MAX_RYU_LINES) {
                        nativeRyujinx.append(line, 0, Math.min(line.length(), 1000)).append('\n');
                    }
                } else if (warning) {
                    shaderWarnings++;
                    if (shaderWarnings <= MAX_SHADER_LINES) {
                        shaders.append(line, 0, Math.min(line.length(), 1000)).append('\n');
                    }
                } else if (low.contains("vulkan:") || low.contains("host1x:")) {
                    statsCount++;
                    if (statsCount <= MAX_STATS_LINES) {
                        stats.append(line, 0, Math.min(line.length(), 1000)).append('\n');
                    }
                }
            }
        } catch (Exception error) {
            out.append("\nERRO ao percorrer log: ").append(error).append('\n');
        }
        out.append("\n=== FALHAS IMPORTANTES (")
           .append(shaderWarnings).append(" linhas, ")
           .append(fswzadd).append(" FSWZADD, ")
           .append(untracked).append(" untracked texture) ===\n");
        out.append(shaders);
        if (shaderWarnings > MAX_SHADER_LINES)
            out.append("... mais ").append(shaderWarnings - MAX_SHADER_LINES).append(" avisos omitidos\n");
        out.append("\n=== TRADUTOR RYUJINX NATIVO VULKAN AO VIVO (")
           .append(ryujinxCount).append(" linhas) ===\n");
        out.append(nativeRyujinx);
        if (ryujinxCount > MAX_RYU_LINES)
            out.append("... mais ").append(ryujinxCount - MAX_RYU_LINES)
               .append(" diagnosticos NativeAOT omitidos\n");
        out.append("\n=== ESTATISTICAS VULKAN (").append(statsCount).append(" linhas) ===\n");
        out.append(stats);
        if (statsCount > MAX_STATS_LINES)
            out.append("... mais ").append(statsCount - MAX_STATS_LINES).append(" estatisticas omitidas\n");
        window(out, log, TAIL_BYTES, true);
        if (perf.length() > 0) {
            out.append("\n=== SNX PERF BEGIN ===\n");
            if (perfTruncated) out.append("SNX_PERF_EXPORT_TRUNCATED\n");
            out.append(perf);
            out.append("=== SNX PERF END ===\n");
        }
        return out.toString();
    }
}
