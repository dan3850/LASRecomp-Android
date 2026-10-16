package com.retroaura.lasrecomp;

import org.libsdl.app.SDLActivity;
import android.os.Bundle;
import android.content.pm.ActivityInfo;
import android.os.Build;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
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
    private GameTouchControls touchControls;

    private void enforceLandscapeFullscreen() {
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        View decor = getWindow().getDecorView();
        int flags = View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;
        decor.setSystemUiVisibility(flags);
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = decor.getWindowInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        }
    }
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

    // Follow Eden's built-in system-font approach: the two fallback TrueType
    // files are shipped with the APK. Nothing needs to be imported manually.
    private void installEdenFonts() {
        File fonts = new File(getFilesDir(), "fonts");
        if (!fonts.isDirectory() && !fonts.mkdirs()) {
            markActivity("Eden fonts FAILED: cannot create fonts directory");
            return;
        }
        String[][] packaged = {
            {"lasrecomp_eden_standard.ttf", "eden_standard.ttf"},
            {"lasrecomp_eden_extended.ttf", "eden_nintendo_ext.ttf"}
        };
        for (String[] entry : packaged) {
            File target = new File(fonts, entry[1]);
            try (InputStream in = getAssets().open(entry[0]);
                 FileOutputStream out = new FileOutputStream(target)) {
                byte[] buffer = new byte[16384];
                int n;
                while ((n = in.read(buffer)) >= 0) {
                    if (n > 0) out.write(buffer, 0, n);
                }
                out.getFD().sync();
                if (target.length() < 4096)
                    throw new java.io.IOException("built-in font truncated");
                markActivity("Eden built-in font ready: " + entry[1] + " " + target.length() + " bytes");
            } catch (Exception e) {
                // Older APK development builds still have the Apache 2.0 fallback.
                if (target.exists()) target.delete();
                markActivity("Eden built-in font FAILED: " + entry[0] + " " + e.getMessage());
            }
        }
    }

    @Override
    public void onCreate(Bundle state) {
        markActivity("onCreate");
        enforceLandscapeFullscreen();
        installFallbackFont();
        installEdenFonts();
        super.onCreate(state);
        enforceLandscapeFullscreen();
        if (mLayout != null) {
            touchControls = new GameTouchControls(this);
            mLayout.addView(touchControls, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            touchControls.bringToFront();
        }
    }
    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) enforceLandscapeFullscreen();
    }
    @Override
    protected void onPause() {
        if (touchControls != null) touchControls.releaseAll();
        super.onPause();
    }
    @Override
    protected void onDestroy() {
        if (touchControls != null) touchControls.releaseAll();
        markActivity("onDestroy");
        super.onDestroy();
    }
    @Override
    protected String[] getLibraries() {
        return new String[] { "SDL3", "main" };
    }
}
