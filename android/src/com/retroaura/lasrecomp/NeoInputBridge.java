package com.retroaura.lasrecomp;

import android.view.KeyEvent;
import org.libsdl.app.SDLActivity;

/**
 * Maps ORIGINAL Ryujinx Neo GamePadButtonInputId ordinal values to LASRecomp.
 * Event dispatch is deliberately independent of RadialGamePad's Kotlin Flow API.
 * This class does not install or imitate the original UI components.
 */
public final class NeoInputBridge {
    // Ordinals from upstream GamePadButtonInputId.kt, including None at index 0.
    public static final int A=1, B=2, X=3, Y=4;
    public static final int L=7, R=8, DPAD_UP=11, DPAD_DOWN=12;
    public static final int DPAD_LEFT=13, DPAD_RIGHT=14;
    public static final int MINUS=15, PLUS=16, LEFT_STICK=17;
    private static final int[] KEY = new int[19];
    private final boolean[] down = new boolean[19];
    private boolean stickUp, stickDown, stickLeft, stickRight;
    static {
        KEY[A]=KeyEvent.KEYCODE_K;
        KEY[B]=KeyEvent.KEYCODE_J;
        KEY[X]=KeyEvent.KEYCODE_L;
        KEY[Y]=KeyEvent.KEYCODE_I;
        KEY[L]=KeyEvent.KEYCODE_Q;
        KEY[R]=KeyEvent.KEYCODE_E;
        KEY[DPAD_UP]=KeyEvent.KEYCODE_W;
        KEY[DPAD_DOWN]=KeyEvent.KEYCODE_S;
        KEY[DPAD_LEFT]=KeyEvent.KEYCODE_A;
        KEY[DPAD_RIGHT]=KeyEvent.KEYCODE_D;
        KEY[MINUS]=KeyEvent.KEYCODE_DEL;
        KEY[PLUS]=KeyEvent.KEYCODE_ENTER;
    }
    public synchronized void button(int id, boolean pressed) {
        if (id <= 0 || id >= KEY.length || KEY[id] == 0 || down[id] == pressed) return;
        down[id]=pressed;
        updateKey(KEY[id]);
    }
    // Maintain shared key state when stick and D-pad overlap.
    private void updateKey(int code) {
        boolean active=false;
        for (int i=0;i<KEY.length;i++) if (KEY[i]==code && down[i]) active=true;
        if (code==KeyEvent.KEYCODE_W) active |= stickUp;
        if (code==KeyEvent.KEYCODE_S) active |= stickDown;
        if (code==KeyEvent.KEYCODE_A) active |= stickLeft;
        if (code==KeyEvent.KEYCODE_D) active |= stickRight;
        boolean prior=pressedKeys[code];
        if (prior==active) return;
        pressedKeys[code]=active;
        if (active) SDLActivity.onNativeKeyDown(code);
        else SDLActivity.onNativeKeyUp(code);
    }
    private final boolean[] pressedKeys=new boolean[256];
    public synchronized void direction(int id, float x, float y) {
        if (id==DPAD_UP) {
            // Original RadialGamePad Cross emits a Direction event, not
            // four separate Button events. Preserve simultaneous diagonals.
            button(DPAD_LEFT, x < -0.35f);
            button(DPAD_RIGHT, x > 0.35f);
            button(DPAD_UP, y < -0.35f);
            button(DPAD_DOWN, y > 0.35f);
            return;
        }
        if (id!=LEFT_STICK) return;
        boolean l=x < -0.35f, r=x > 0.35f, u=y < -0.35f, d=y > 0.35f;
        stickLeft=l; stickRight=r; stickUp=u; stickDown=d;
        updateKey(KeyEvent.KEYCODE_A); updateKey(KeyEvent.KEYCODE_D);
        updateKey(KeyEvent.KEYCODE_W); updateKey(KeyEvent.KEYCODE_S);
    }
    public synchronized void releaseAll() {
        for (int i=0;i<down.length;i++) down[i]=false;
        stickLeft=stickRight=stickUp=stickDown=false;
        for (int code=0;code<pressedKeys.length;code++) {
            if (pressedKeys[code]) {
                pressedKeys[code]=false;
                SDLActivity.onNativeKeyUp(code);
            }
        }
    }
}
