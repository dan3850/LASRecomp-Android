package com.retroaura.lasrecomp;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import org.libsdl.app.SDLActivity;

/**
 * A different Android process runs the pinned GPLv3 ScarletNX runtime.
 * Its own SDL3/CPU/Horizon/Vulkan startup is required for ABI-12 game code.
 * No LASRecomp Cpu* or Vulkan contexts are passed across engines.
 */
public final class MarioSnxGameActivity extends SDLActivity {
    private void stage(String message) {
        Log.i("MarioSNX", "GUEST PROCESS " + message);
        try (FileOutputStream file = new FileOutputStream(
                new File(getFilesDir(), "mario-snx-launch.log"), true)) {
            file.write((System.currentTimeMillis() + " [:snx] " + message + "\n")
                    .getBytes(StandardCharsets.UTF_8));
            file.getFD().sync();
        } catch (Exception error) {
            Log.e("MarioSNX", "Could not write :snx stage", error);
        }
    }

    @Override public void onCreate(Bundle savedState) {
        stage("SDL_ACTIVITY_ONCREATE_ENTERED: child process started");
        try {
            super.onCreate(savedState);
            stage("SDL_ACTIVITY_ONCREATE_RETURNED");
        } catch (Throwable error) {
            stage("SDL_ACTIVITY_ONCREATE_FAILED: " + error.toString());
            throw error;
        }
    }

    @Override protected String[] getLibraries() {
        stage("SDL_GET_LIBRARIES: loading libscarletnx.so");
        return new String[]{"scarletnx"};
    }
    @Override protected String getMainFunction() { return "main"; }

    @Override protected String[] getArguments() {
        // Called on the SDL entry thread after the native SDL JNI is loaded,
        // immediately before libscarletnx.so's main(). ScarletNX uses HOME
        // (or XDG_DATA_HOME) to find its persistent console users folder.
        // Unlike the official ScarletNX app, this launcher has no HOME set.
        File home = new File(getFilesDir(), "snx-home");
        File data = new File(home, ".local/share");
        if ((!home.isDirectory() && !home.mkdirs()) ||
                (!data.isDirectory() && !data.mkdirs())) {
            stage("SDL_HOME_FAILED: cannot create " + data);
            return new String[]{"--settings"};
        }
        try {
            SDLActivity.nativeSetenv("HOME", home.getAbsolutePath());
            SDLActivity.nativeSetenv("XDG_DATA_HOME", data.getAbsolutePath());
            SDLActivity.nativeSetenv("SNX_BOOT_TRACE",
                    new File(getFilesDir(), "mario-snx-native.log").getAbsolutePath());
            stage("SDL_ENV_READY: HOME=" + home.getAbsolutePath() +
                    " XDG_DATA_HOME=" + data.getAbsolutePath());
        } catch (Throwable error) {
            stage("SDL_ENV_FAILED: " + error);
            return new String[]{"--settings"};
        }
        String externalRomfs = getIntent().getStringExtra("snx_romfs_source");
        if (externalRomfs != null && new File(externalRomfs).isDirectory()) {
            SDLActivity.nativeSetenv("SNX_EXTERNAL_ROMFS", externalRomfs);
            stage("SDL_ROMFS_ENV_READY: " + externalRomfs);
        } else {
            stage("SDL_ROMFS_MISSING: " + externalRomfs);
        }
        String base = getIntent().getStringExtra("snx_game_base");
        if (base == null || base.isEmpty()) {
            stage("SDL_GET_ARGUMENTS: missing game path, refusing to run");
            return new String[]{"--settings"};
        }
        stage("SDL_GET_ARGUMENTS: invoking ScarletNX main with game base " + base);
        return new String[]{"--game=" + base, "--log=2"};
    }

    /** ScarletNX's fatal-screen log sharing callback, if the renderer reaches it. */
    public void share(String path) {
        try {
            File file = new File(path);
            if (!file.isFile()) return;
            Intent intent = new Intent(Intent.ACTION_SEND);
            intent.setType("text/plain");
            // The log stays in this package's files; the parent app has a
            // "Ver último log" reader. Do not leak a file:// URI to other apps.
            intent.putExtra(Intent.EXTRA_TEXT,
                "ScarletNX: log em " + file.getName() +
                ". Volte ao Mario ScarletNX TESTE e use Ver último log.");
            startActivity(Intent.createChooser(intent, "Relatório de inicialização"));
        } catch (Exception ignored) { }
    }

    // ScarletNX's main() has process-long singleton state. Never reenter it
    // after SDL has destroyed its activity; the launcher uses another process.
    @Override protected void onDestroy() {
        stage("SDL_ACTIVITY_ONDESTROY");
        super.onDestroy();
        System.exit(0);
    }
}
