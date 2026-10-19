package com.retroaura.lasrecomp;

import android.view.KeyEvent;
import org.libsdl.app.SDLActivity;

/**
 * Ryujinx Neo GamePadButtonInputId -> actual LASRecomp Switch HID bindings.
 *
 * Source of truth: runtime/hle/bindings.c and runtime/hle/input.c.
 * - Buttons / D-pad are SDL keyboard events and honor the game's bindings.
 * - Both touch sticks send continuous float axes via JNI into nn::hid.
 * - Nintendo A=east, B=south, X=north, Y=west (not Xbox face positions).
 * Home is an app-owned menu shortcut: SDL F1, NOT the game's Plus button.
 */
public final class NeoInputBridge {
    // Exact ordinal values in Ryujinx Neo GamePadButtonInputId.kt.
    public static final int A=1, B=2, X=3, Y=4;
    public static final int LEFT_STICK_BUTTON=5, RIGHT_STICK_BUTTON=6;
    public static final int L=7, R=8, ZL=9, ZR=10, DPAD_UP=11, DPAD_DOWN=12;
    public static final int DPAD_LEFT=13, DPAD_RIGHT=14;
    public static final int MINUS=15, PLUS=16, LEFT_STICK=17, RIGHT_STICK=18;

    private static final int[] KEY = new int[19];
    private final boolean[] down = new boolean[19];
    private final boolean[] pressedKeys = new boolean[256];
    private boolean homeDown;
    private float leftX, leftY, rightX, rightY;

    static {
        // Exact default SDL keyboard bindings from runtime/hle/bindings.c.
        KEY[A]=KeyEvent.KEYCODE_K;
        KEY[B]=KeyEvent.KEYCODE_J;
        KEY[X]=KeyEvent.KEYCODE_L;
        KEY[Y]=KeyEvent.KEYCODE_I;
        KEY[LEFT_STICK_BUTTON]=KeyEvent.KEYCODE_F;
        KEY[RIGHT_STICK_BUTTON]=KeyEvent.KEYCODE_NUMPAD_0;
        KEY[L]=KeyEvent.KEYCODE_Q;
        KEY[R]=KeyEvent.KEYCODE_E;
        KEY[ZL]=KeyEvent.KEYCODE_1;
        KEY[ZR]=KeyEvent.KEYCODE_3;
        KEY[DPAD_UP]=KeyEvent.KEYCODE_DPAD_UP;
        KEY[DPAD_DOWN]=KeyEvent.KEYCODE_DPAD_DOWN;
        KEY[DPAD_LEFT]=KeyEvent.KEYCODE_DPAD_LEFT;
        KEY[DPAD_RIGHT]=KeyEvent.KEYCODE_DPAD_RIGHT;
        KEY[MINUS]=KeyEvent.KEYCODE_DEL;
        KEY[PLUS]=KeyEvent.KEYCODE_ENTER;
    }

    public synchronized void button(int id, boolean pressed) {
        if (id <= 0 || id >= KEY.length || KEY[id] == 0 || down[id] == pressed) return;
        down[id] = pressed;
        updateKey(KEY[id], pressed);
    }

    private void updateKey(int key, boolean pressed) {
        if (key < 0 || key >= pressedKeys.length || pressedKeys[key] == pressed) return;
        pressedKeys[key] = pressed;
        if (pressed) SDLActivity.onNativeKeyDown(key);
        else SDLActivity.onNativeKeyUp(key);
    }

    /** Independent app menu key; F1 toggles the real in-game LASRecomp menu. */
    public synchronized void home(boolean pressed) {
        if (homeDown == pressed) return;
        homeDown = pressed;
        updateKey(KeyEvent.KEYCODE_F1, pressed);
    }

    public synchronized void direction(int id, float x, float y) {
        if (id == DPAD_UP) {
            // Neo's Cross emits one Direction with two axes, including diagonals.
            // The guest D-pad is independent of the left stick.
            button(DPAD_LEFT, x < -0.35f);
            button(DPAD_RIGHT, x > 0.35f);
            button(DPAD_UP, y < -0.35f);
            button(DPAD_DOWN, y > 0.35f);
            return;
        }
        if (id != LEFT_STICK && id != RIGHT_STICK) return;
        if (!Float.isFinite(x)) x = 0f;
        if (!Float.isFinite(y)) y = 0f;
        x = Math.max(-1f, Math.min(1f, x));
        y = Math.max(-1f, Math.min(1f, y));
        if (id == LEFT_STICK) {
            if (leftX == x && leftY == y) return;
            leftX = x;
            leftY = y;
        } else {
            if (rightX == x && rightY == y) return;
            rightX = x;
            rightY = y;
        }
        // The original Neo uses inputSetStickAxis(1/2, x, -y).
        // In LASRecomp, libmain JNI -> runtime/hle/input.c performs -y
        // and writes the full-scale Switch nn::hid analog values.
        try {
            GameSDLActivity.nativeSetNeoStick(id == LEFT_STICK ? 1 : 2, x, y);
        } catch (UnsatisfiedLinkError error) {
            android.util.Log.e("LASRecomp-Neo", "Native touch stick bridge unavailable", error);
        }
    }

    public synchronized void releaseAll() {
        for (int i = 0; i < down.length; i++) down[i] = false;
        homeDown = false;
        leftX = leftY = rightX = rightY = 0f;
        for (int key = 0; key < pressedKeys.length; key++) {
            if (pressedKeys[key]) {
                pressedKeys[key] = false;
                SDLActivity.onNativeKeyUp(key);
            }
        }
        try {
            GameSDLActivity.nativeSetNeoStick(1, 0f, 0f);
            GameSDLActivity.nativeSetNeoStick(2, 0f, 0f);
        } catch (UnsatisfiedLinkError error) {
            android.util.Log.e("LASRecomp-Neo", "Native touch stick release unavailable", error);
        }
    }
}
