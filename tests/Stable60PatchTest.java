package com.retroaura.lasrecomp;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

public final class Stable60PatchTest {
    private static int checks;
    private static void require(boolean value) { ++checks; if (!value) throw new AssertionError(); }
    private static void refused(String source) throws Exception {
        try { Stable60Patch.validate(source); throw new AssertionError("accepted unsupported mod"); }
        catch (IOException expected) { ++checks; }
    }
    public static void main(String[] args) throws Exception {
        String patch = Stable60Patch.CANONICAL;
        Stable60Patch.validate(patch);
        Stable60Patch.validate(patch.replace("\n", "\r\n").replace("@enabled", "@enabled // comment"));
        Stable60Patch.validate(patch.replace("@enabled", "@flag print_values\n@enabled"));
        Stable60Patch.validate(patch + "@theboy181\n");
        Stable60Patch.validate(patch.replace("@enabled", "@disabled\n00000000 FFFFFFFF\n@enabled"));
        // Header-relative IPS offsets are also accepted when shift is zero.
        Stable60Patch.validate(patch.replace("offset_shift 0x100", "offset_shift 0")
            .replace("01019608", "01019708").replace("01019628", "01019728"));
        refused(patch.replace(Stable60Patch.BUILD_ID, "0000000000000000000000000000000000000000"));
        refused(patch.replace("1F2003D5", "00000000"));
        refused(patch.replace("01019628", "0101962C"));
        refused(patch.replace("01019628 1F2003D5\n", ""));
        refused(patch.replace("@enabled", "@enabled\n01019608 1F2003D5"));
        refused(patch.replace("@enabled", "@enabled\n00000000 1F2003D5"));
        refused(patch.replace("@flag offset_shift 0x100\n", ""));
        refused(patch.replace("@flag offset_shift 0x100", "@flag offset_shift banana"));
        refused(patch.replace("@flag offset_shift 0x100", "@flag offset_shift 0x200"));
        refused(patch.replace("@enabled", "@unknown\n@enabled"));
        refused(patch.replace("@enabled", "@disabled"));
        refused(new String(new char[Stable60Patch.MAX_BYTES + 1]));
        try {
            Stable60Patch.read(new ByteArrayInputStream(new byte[Stable60Patch.MAX_BYTES + 1]));
            throw new AssertionError("accepted oversized input");
        } catch (IOException expected) { ++checks; }
        File directory = new File(args[0], "mods");
        require(!Stable60Patch.imported(directory));
        require(!Stable60Patch.enabled(directory));
        Stable60Patch.importPatch(directory, patch);
        require(Stable60Patch.imported(directory));
        require(!Stable60Patch.enabled(directory));
        try { Stable60Patch.setEnabled(directory, true, false); throw new AssertionError(); }
        catch (IOException expected) { ++checks; }
        Stable60Patch.setEnabled(directory, true, true);
        require(Stable60Patch.enabled(directory));
        byte[] original = Files.readAllBytes(new File(directory, Stable60Patch.IMPORTED).toPath());
        try { Stable60Patch.importPatch(directory, patch.replace("1F2003D5", "12345678")); throw new AssertionError(); }
        catch (IOException expected) { ++checks; }
        require(Arrays.equals(original, Files.readAllBytes(new File(directory, Stable60Patch.IMPORTED).toPath())));
        require(Stable60Patch.enabled(directory));
        Stable60Patch.setEnabled(directory, false, true);
        require(!Stable60Patch.enabled(directory));
        require(Stable60Patch.imported(directory));
        require(directory.listFiles((d, name) -> name.endsWith(".partial")).length == 0);
        System.out.println("PCHTXT validation, compatibility gate, activation and preservation: " + checks + " checks PASS");
    }
}
