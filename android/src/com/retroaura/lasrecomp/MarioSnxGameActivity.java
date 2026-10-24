package com.retroaura.lasrecomp;

import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
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
            hideSystemBars();
            stage("SDL_ACTIVITY_ONCREATE_RETURNED");
        } catch (Throwable error) {
            stage("SDL_ACTIVITY_ONCREATE_FAILED: " + error.toString());
            throw error;
        }
    }

    private void hideSystemBars() {
        // SDL 3.4.18 initially requests a windowed style. Clear that flag
        // again when returning from Android UI; native startup also receives
        // --fullscreen so SDL and the renderer agree on the window's size.
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_FORCE_NOT_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController bars = getWindow().getInsetsController();
            if (bars != null) {
                bars.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                bars.hide(WindowInsets.Type.systemBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    @Override protected void onResume() {
        super.onResume();
        hideSystemBars();
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemBars();
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
        // Castlevania-only: never affect Mario and never read shader modules
        // from public Downloads; they must be explicitly imported to app-private storage.
        boolean ryujinx = getIntent().getBooleanExtra("snx_ryujinx_bridge", false);
        if (ryujinx && new File(base).getName().equals("0100BA4026E94000")) {
            File pack = new File(getFilesDir(),
                    "snx-games/0100BA4026E94000/ryujinx-bridge.snxrbr");
            if (pack.isFile() && pack.canRead() && pack.length() >= 1024
                    && pack.length() <= 4 * 1024 * 1024) {
                SDLActivity.nativeSetenv("SNX_RYUJINX_BRIDGE", pack.getAbsolutePath());
                stage("SDL_RYUJINX_BRIDGE_OPTIN: private pack ready, native fallback retained");
            } else {
                stage("SDL_RYUJINX_BRIDGE_MISSING: continuing with native translator");
            }
        }
        boolean zelda = new File(base).getName().equals("01006BB00C6F0000");
        int perfMode = zelda ? getIntent().getIntExtra("snx_perf_mode", 0) : 0;
        if (zelda) ScarletNxExitInfo.state(this, "Zelda D24-integration=2 requested=" +
                getIntent().getBooleanExtra("snx_d24_copies", false) + " perf=" + perfMode);
        SDLActivity.nativeSetenv("SNX_PERF", perfMode > 0 ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_KNOWN_COMPLETE",
                zelda && getIntent().getBooleanExtra("snx_known_complete", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_RYU_PERSIST",
                zelda && getIntent().getBooleanExtra("snx_ryu_persist", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_HASH_SPAN",
                zelda && getIntent().getBooleanExtra("snx_hash_span", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_TRANSFER_REUSE",
                zelda && getIntent().getBooleanExtra("snx_transfer_reuse", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_UNIFORM_STREAM",
                zelda && getIntent().getBooleanExtra("snx_uniform_stream", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_CLEAR_LOAD",
                zelda && getIntent().getBooleanExtra("snx_clear_load", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_UB_EXTENT",
                zelda && getIntent().getBooleanExtra("snx_ub_extent", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_BIND_REUSE",
                zelda && getIntent().getBooleanExtra("snx_bind_reuse", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_VB_POOL",
                zelda && getIntent().getBooleanExtra("snx_vb_pool", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_DEPTH_RANGE",
                zelda && getIntent().getBooleanExtra("snx_depth_range", false) ? "1" : "0");
        SDLActivity.nativeSetenv("SNX_VK_D24_PACK",
                zelda && getIntent().getBooleanExtra("snx_d24_copies", false) ? "1" : "0");
        String shadowDir = zelda ? getIntent().getStringExtra("snx_shadow_capture_dir") : null;
        SDLActivity.nativeSetenv("SNX_SHADOW_CAPTURE_DIR", shadowDir == null ? "" : shadowDir);
        String effectDepthDir = zelda ? getIntent().getStringExtra("snx_effect_depth_dir") : null;
        SDLActivity.nativeSetenv("SNX_EFFECT_DEPTH_DIR", effectDepthDir == null ? "" : effectDepthDir);
        // Each trial has a fresh child process. Neither variable needs a "0"
        // value: BUFFER_STATS checks presence and gpuprof warns on disabled "0".
        if (perfMode == 2) {
            SDLActivity.nativeSetenv("SNX_VK_GPU_PROFILE", "1");
            SDLActivity.nativeSetenv("SNX_VK_BUFFER_STATS", "1");
            SDLActivity.nativeSetenv("SNX_GFX_DIAG", "1");
        }
        stage("SDL_PERF_MODE=" + perfMode);
        // Real C# translation, explicitly selected before starting the child.
        if (getIntent().getBooleanExtra("snx_ryujinx_native_probe", false)
                && (zelda || new File(base).getName().equals("0100BA4026E94000"))) {
            File nativeLib = new File(getApplicationInfo().nativeLibraryDir,
                    "libRyujinxShaderNative.so");
            if (nativeLib.isFile() && nativeLib.canRead()) {
                SDLActivity.nativeSetenv("SNX_RYUJINX_NATIVE_PROBE", "1");
                stage("SDL_RYUJINX_NATIVE_VULKAN_ON: Ryujinx NativeAOT auto shader bridge enabled, ScarletNX fallback available");
            } else {
                stage("SDL_RYUJINX_NATIVE_VULKAN_MISSING: packaged .so absent; ScarletNX native fallback");
            }
        }
        // Castlevania-only, explicit opt-in; other APKs keep their CLI unchanged.
        boolean shaderCaptures = getIntent().getBooleanExtra("snx_shader_captures", false);
        if (shaderCaptures) stage("SDL_SHADER_CAPTURE_ON: recording Maxwell .snxs files");
        String source = getIntent().getStringExtra("snx_source_dump");
        if (source != null) {
            File dump = new File(source);
            if (!dump.isFile() || !dump.canRead()) {
                stage("SDL_SOURCE_INVALID: cannot read selected XCI");
                return new String[]{"--settings"};
            }
            stage("SDL_SOURCE_READY: loading ExeFS and RomFS from selected XCI");
            // Pinned ScarletNX 34853ee accepts --source=PATH through ini_override,
            // then fs.c dump_open reads from the encrypted container in-place.
            if (shaderCaptures) {
                return new String[]{"--game=" + base, "--source=" + dump.getAbsolutePath(),
                        "--log=2", "--diag=1", "--fullscreen"};
            }
            return new String[]{"--game=" + base, "--source=" + dump.getAbsolutePath(),
                    "--log=2", "--fullscreen"};
        }
        stage("SDL_GET_ARGUMENTS: invoking ScarletNX main with game base " + base);
        if (shaderCaptures)
            return new String[]{"--game=" + base, "--log=2", "--diag=1", "--fullscreen"};
        return new String[]{"--game=" + base, "--log=2", "--fullscreen"};
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
