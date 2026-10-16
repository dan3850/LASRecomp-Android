package com.retroaura.lasrecomp;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** PCHTXT compatibility for the two explicitly prepared Stable 60fps v2 sites. */
public final class Stable60Patch {
    public static final String BUILD_ID = "AE16F71E002AF8CB059A9A74C4D90F34BA984892";
    public static final String IMPORTED = "stable60-v2.pchtxt";
    public static final String ENABLED = "stable60-v2.enabled";
    public static final int MAX_BYTES = 65536;
    public static final String CANONICAL = "@nsobid-" + BUILD_ID +
        "\n# Stable 60fps v2 - theboy181\n@flag offset_shift 0x100\n@enabled\n" +
        "01019608 1F2003D5\n01019628 1F2003D5\n@stop\n";

    private Stable60Patch() {}

    public static void validate(String source) throws IOException {
        if (source.length() > MAX_BYTES) throw new IOException("Mod grande demais.");
        boolean enabled = false, matchingBuild = false;
        long shift = 0;
        Set<Long> sites = new HashSet<>();
        for (String raw : source.replace("\uFEFF", "").split("\\r?\\n")) {
            String line = raw.split("//", 2)[0].split("#", 2)[0].trim();
            if (line.isEmpty()) continue;
            String lower = line.toLowerCase(Locale.ROOT);
            if (lower.equals("@stop")) break;
            if (lower.startsWith("@nsobid-")) {
                String id = line.substring(8).trim().toUpperCase(Locale.ROOT);
                if (matchingBuild || !(id.equals(BUILD_ID) || id.equals(BUILD_ID + "000000000000000000000000")))
                    throw new IOException("Build ID incompatível. Este mod exige Link's Awakening v1.0.0.");
                matchingBuild = true;
            } else if (lower.equals("@enabled")) {
                enabled = true;
            } else if (lower.equals("@disabled")) {
                enabled = false;
            } else if (lower.equals("@flag print_values")) {
                // Informational IPSwitch flag; it changes no patch bytes.
            } else if (lower.startsWith("@flag offset_shift ")) {
                try { shift = Long.decode(line.substring(19).trim()); }
                catch (NumberFormatException error) { throw new IOException("offset_shift inválido."); }
                if (shift != 0 && shift != 0x100) throw new IOException("offset_shift não suportado.");
            } else if (lower.startsWith("@")) {
                throw new IOException("Diretiva PCHTXT não suportada: " + line);
            } else if (enabled) {
                String[] fields = line.split("\\s+");
                if (fields.length != 2 || !fields[0].matches("[0-9a-fA-F]{1,8}") ||
                    !fields[1].equalsIgnoreCase("1F2003D5"))
                    throw new IOException("Nesta versão, somente o Stable 60fps v2 é compatível com o menu.");
                long offset = Long.parseLong(fields[0], 16) + shift - 0x100;
                if ((offset != 0x01019608L && offset != 0x01019628L) || !sites.add(offset))
                    throw new IOException("O mod contém instruções fora dos dois pontos preparados.");
            }
        }
        if (!matchingBuild || sites.size() != 2)
            throw new IOException("Não encontrei os dois patches do Stable 60fps v2 e seu Build ID.");
    }

    public static String read(InputStream stream) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int n;
        while ((n = stream.read(buffer)) != -1) {
            if (output.size() + n > MAX_BYTES) throw new IOException("Arquivo de mod grande demais.");
            output.write(buffer, 0, n);
        }
        return new String(output.toByteArray(), StandardCharsets.UTF_8);
    }

    private static void atomicWrite(File directory, String name, String value) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Não consegui criar a pasta de mods.");
        File temporary = File.createTempFile(".mod-", ".partial", directory);
        try {
            try (FileOutputStream stream = new FileOutputStream(temporary)) {
                stream.write(value.getBytes(StandardCharsets.UTF_8));
                stream.getFD().sync();
            }
            if (!temporary.renameTo(new File(directory, name))) throw new IOException("Não consegui salvar o mod.");
        } finally { temporary.delete(); }
    }

    public static void importPatch(File directory, String source) throws IOException {
        validate(source); // Complete validation before replacing an existing import.
        atomicWrite(directory, IMPORTED, CANONICAL);
    }

    public static boolean imported(File directory) {
        try (InputStream stream = new FileInputStream(new File(directory, IMPORTED))) {
            validate(read(stream));
            return true;
        } catch (IOException error) { return false; }
    }

    public static boolean enabled(File directory) {
        if (!imported(directory)) return false;
        try (InputStream stream = new FileInputStream(new File(directory, ENABLED))) {
            return read(stream).equals(BUILD_ID + "\n");
        } catch (IOException error) { return false; }
    }

    public static void setEnabled(File directory, boolean enabled, boolean prepared) throws IOException {
        if (enabled && (!prepared || !imported(directory)))
            throw new IOException("Importe o mod e a biblioteca preparada para o menu antes de ativar.");
        atomicWrite(directory, ENABLED, enabled ? BUILD_ID + "\n" : "disabled\n");
    }
}
