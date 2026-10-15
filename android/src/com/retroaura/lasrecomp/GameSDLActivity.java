package com.retroaura.lasrecomp;

import org.libsdl.app.SDLActivity;

/**
 * Window, lifecycle, audio and input integration using SDL3's official
 * Android Activity. The game cannot be entered until the full native
 * LASRecomp runtime and user-generated game code are available.
 *
 * This Activity is intentionally not exported or used as the launcher yet.
 * It does not use Termux.
 */
public final class GameSDLActivity extends SDLActivity {
    @Override
    protected String[] getLibraries() {
        return new String[] { "SDL3", "main" };
    }
}
