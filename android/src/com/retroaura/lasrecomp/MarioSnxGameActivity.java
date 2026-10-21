package com.retroaura.lasrecomp;

import android.content.Intent;
import android.net.Uri;
import java.io.File;
import org.libsdl.app.SDLActivity;

/**
 * A different Android process runs the unmodified GPLv3 ScarletNX runtime.
 * Its own SDL3/CPU/Horizon/Vulkan startup is required for ABI-12 game code.
 * No LASRecomp Cpu* or Vulkan contexts are passed across engines.
 */
public final class MarioSnxGameActivity extends SDLActivity {
    @Override protected String[] getLibraries() { return new String[]{"scarletnx"}; }
    @Override protected String getMainFunction() { return "main"; }

    @Override protected String[] getArguments() {
        String base = getIntent().getStringExtra("snx_game_base");
        if (base == null || base.isEmpty()) return new String[]{"--settings"};
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
        super.onDestroy();
        System.exit(0);
    }
}
