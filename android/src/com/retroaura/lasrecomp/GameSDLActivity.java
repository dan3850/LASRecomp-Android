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
    private static native boolean nativeRequestGraphicsCapture();
    // Routed by libmain.so to the existing nn::hid input engine. SDL keyboard
    // codes cannot represent partial stick deflection, so these stay analog.
    static native void nativeSetNeoStick(int stick, float x, float y);
    /** Exact native-library folder required by AdrenoTools hooks. */
    public String getVulkanDriverFilesDirectory() {
        return getFilesDir().getAbsolutePath();
    }
    public String getVulkanHookLibraryDirectory() {
        return getApplicationInfo().nativeLibraryDir;
    }
    private GameTouchControls touchControls;
    private NeoInputBridge neoInput;
    private Object neoControls;
    private android.net.Uri selectedGameTree;
    private GameDocumentBridge.RomfsIndex romfsIndex;

    /** Called by SDL's native entry point through JNI on the active Activity. */
    public String getExternalGameRoot() {
        if (selectedGameTree == null) return null;
        // A document URI is not a POSIX directory. Native code must not
        // pass it to fopen, stat or opendir.
        return selectedGameTree.toString();
    }

    /** Native JNI can call this method and then use the returned read-only fd. */
    public synchronized int openGameDocumentFd(byte[] utf8Path) throws java.io.IOException {
        if (selectedGameTree == null) throw new java.io.FileNotFoundException("No external game folder selected");
        String relativePath = new String(utf8Path, StandardCharsets.UTF_8);
        if (relativePath.startsWith("romfs/") && romfsIndex != null)
            return romfsIndex.open(this, selectedGameTree, relativePath.substring(6));
        return GameDocumentBridge.openReadFd(this, selectedGameTree, relativePath);
    }

    /** Called once per native mount; UTF-8 bytes avoid JNI modified-UTF-8 paths. */
    public synchronized byte[] getGameRomfsIndex() throws java.io.IOException {
        if (selectedGameTree == null) throw new java.io.FileNotFoundException("Pasta externa não selecionada");
        GameDocumentBridge.RomfsIndex fresh = GameDocumentBridge.indexRomfs(this, selectedGameTree);
        fresh.validateAccess(this, selectedGameTree);
        romfsIndex = fresh;
        return fresh.manifest();
    }

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

    @Override
    public void onCreate(Bundle state) {
        markActivity("onCreate");
        String tree = getIntent().getStringExtra("game_tree_uri");
        if (tree != null) {
            android.net.Uri candidate = android.net.Uri.parse(tree);
            if (GameDocumentBridge.hasPermission(this, candidate)) {
                selectedGameTree = candidate;
                markActivity("SAF game folder permission verified");
            } else markActivity("SAF game folder permission missing");
        }
        enforceLandscapeFullscreen();
        installFallbackFont();
        super.onCreate(state);
        enforceLandscapeFullscreen();
        if (mLayout != null) {
            // Prefer the original RadialGamePad UI when the optional Kotlin
            // implementation and all its runtime dependencies are packaged.
            // Retain the existing working controls for ordinary Java builds.
            try {
                Class<?> type = Class.forName("com.retroaura.lasrecomp.NeoRadialControls");
                neoInput = new NeoInputBridge();
                neoControls = type.getConstructor(android.app.Activity.class, NeoInputBridge.class)
                        .newInstance(this, neoInput);
                View original = (View) type.getMethod("getView").invoke(neoControls);
                mLayout.addView(original, new ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                original.bringToFront();
                markActivity("original RadialGamePad mounted");
                // Keep the original Android crash handler and save touch-thread
                // exceptions so the next graphics ZIP contains the Java stack.
                NeoCrashReporter.install(this);
            } catch (ClassNotFoundException missingOptionalModule) {
                installLegacyTouchControls();
            } catch (Exception | LinkageError error) {
                markActivity("RadialGamePad unavailable: " + error);
                neoControls = null;
                neoInput = null;
                installLegacyTouchControls();
            }
        }
    }
    private void installLegacyTouchControls() {
        touchControls = new GameTouchControls(this);
        mLayout.addView(touchControls, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        touchControls.bringToFront();
    }
    private void releaseNeoControls() {
        if (neoInput != null) neoInput.releaseAll();
    }
    private void closeNeoControls() {
        if (neoControls != null) {
            try { neoControls.getClass().getMethod("close").invoke(neoControls); }
            catch (Exception error) { markActivity("RadialGamePad close: " + error); }
            neoControls = null;
        }
        releaseNeoControls();
    }
    // The temporary on-screen CAPTURAR LOG button and its polling UI are
    // intentionally absent. Keep the native capture entry point and
    // GraphicsDiagnostics ZIP infrastructure for future diagnostics.
    @Override protected void onActivityResult(int request, int result, android.content.Intent data) {
        if (!GraphicsDiagnostics.handleResult(this, request, result, data)) super.onActivityResult(request, result, data);
    }
    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) enforceLandscapeFullscreen();
    }
    @Override
    protected void onPause() {
        if (touchControls != null) touchControls.releaseAll();
        releaseNeoControls();
        super.onPause();
    }
    @Override
    protected void onDestroy() {
        if (touchControls != null) touchControls.releaseAll();
        closeNeoControls();
        markActivity("onDestroy");
        super.onDestroy();
    }
    @Override
    protected String[] getLibraries() {
        return new String[] { "SDL3", "main" };
    }
}
