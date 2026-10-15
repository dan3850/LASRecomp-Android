package com.retroaura.lasrecomp;

import org.libsdl.app.SDLActivity;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * Window, lifecycle, audio and input integration using SDL3's official
 * Android Activity. The game cannot be entered until the full native
 * LASRecomp runtime and user-generated game code are available.
 *
 * This Activity is intentionally not exported or used as the launcher yet.
 * It does not use Termux.
 */
public final class GameSDLActivity extends SDLActivity {
    private void markActivity(String message) {
        try (FileOutputStream out = new FileOutputStream(
                 new File(getFilesDir(), "lasrecomp_boot.txt"), true)) {
            out.write(("[activity] " + message + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {}
    }
    private void installFallbackFont() {
        // The game expects a Switch system font, but no proprietary Switch
        // fonts ship with the app. Copy the Apache-2.0 static fallback font
        // already included in Dear ImGui to our private data directory.
        try {
            File fonts = new File(getFilesDir(), "fonts");
            if (!fonts.isDirectory() && !fonts.mkdirs())
                throw new java.io.IOException("cannot create fonts directory");
            File result = new File(fonts, "android_fallback.ttf");
            try (InputStream in = getAssets().open("lasrecomp_font.ttf");
                 FileOutputStream out = new FileOutputStream(result)) {
                byte[] buffer = new byte[16384];
                int count;
                while ((count = in.read(buffer)) != -1)
                    out.write(buffer, 0, count);
                out.getFD().sync();
            }
            if (result.length() < 100000)
                throw new java.io.IOException("font missing or truncated");
            markActivity("static font ready: " + result.length() + " bytes");
        } catch (Exception error) {
            markActivity("static font FAILED: " + error.getMessage());
        }
    }

    @Override
    public void onCreate(Bundle state) {
        markActivity("onCreate");
        installFallbackFont();
        super.onCreate(state);
    }
    @Override
    protected void onDestroy() {
        markActivity("onDestroy");
        super.onDestroy();
    }
    @Override
    protected String[] getLibraries() {
        return new String[] { "SDL3", "main" };
    }
}
