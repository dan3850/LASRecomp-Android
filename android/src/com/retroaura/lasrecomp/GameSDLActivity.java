package com.retroaura.lasrecomp;

import org.libsdl.app.SDLActivity;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
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
    @Override
    public void onCreate(Bundle state) {
        markActivity("onCreate");
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
