package com.retroaura.lasrecomp;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.SparseIntArray;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import org.libsdl.app.SDLActivity;

/**
 * Touch-only Nintendo-style controller, inspired by the Android control
 * arrangement of Kenjinx/Ryujinx Neo (MIT, Kenji-NX Team and Contributors).
 * Rendering and multi-touch handling are native Android View code, not the
 * external RadialGamePad dependency. See docs/android-touch-controls.md.
 *
 * Switch buttons are sent through the existing SDL keyboard bindings so game
 * menus keep working. The two sticks use full-resolution native analog axes.
 * No Vulkan, audio, guest timing or game binary changes.
 */
public final class GameTouchControls extends View {
    private static final int UP=0, DOWN=1, LEFT=2, RIGHT=3;
    private static final int A=4, B=5, X=6, Y=7, L=8, R=9;
    private static final int ZL=10, ZR=11, PLUS=12, MINUS=13, L3=14, R3=15;
    private static final int LEFT_STICK=16, RIGHT_STICK=17, BUTTON_COUNT=16;
    private static final String[] LABELS = {
        "▲", "▼", "◀", "▶", "A", "B", "X", "Y",
        "L", "R", "ZL", "ZR", "+", "−", "L3", "R3"
    };
    // Match the existing LASRecomp keyboard defaults. Crucially, DPAD arrows
    // are NOT WASD: the virtual left stick is a separate analog input.
    private static final int[] KEYS = {
        KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN,
        KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT,
        KeyEvent.KEYCODE_K, KeyEvent.KEYCODE_J,
        KeyEvent.KEYCODE_L, KeyEvent.KEYCODE_I,
        KeyEvent.KEYCODE_Q, KeyEvent.KEYCODE_E,
        KeyEvent.KEYCODE_1, KeyEvent.KEYCODE_3,
        KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_DEL,
        KeyEvent.KEYCODE_F, KeyEvent.KEYCODE_NUMPAD_0
    };

    // The JNI bridge lives in libmain.so and forwards to the active runtime.
    // A failed early call, before the runtime is loaded, is harmless.
    private static native boolean nativeSetTouchAxes(
            float leftX, float leftY, float rightX, float rightY);

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rect = new RectF();
    private final float[] cx = new float[18], cy = new float[18], radius = new float[18];
    private final int[] held = new int[BUTTON_COUNT];
    private final SparseIntArray pointerToControl = new SparseIntArray();
    private final float[] axes = new float[4];
    private final float density;
    private boolean ready;

    public GameTouchControls(Context context) {
        super(context);
        density = getResources().getDisplayMetrics().density;
        setClickable(true);
        setFocusable(false);
        setWillNotDraw(false);
    }

    private void place(int index, float x, float y, float r) {
        cx[index] = x;
        cy[index] = y;
        radius[index] = r;
    }

    private void positionControls(int w, int h) {
        final float d = density;
        final float button = Math.max(20f*d, Math.min(30f*d, h*0.066f));
        final float analog = Math.max(41f*d, Math.min(65f*d, h*0.158f));
        final float edge = analog + 16f*d;
        final float step = button*1.36f;
        // Neo's layout: left analog above the left D-pad; ABXY above right
        // analog. The groups stay apart even on a narrow landscape phone.
        final float leftX = edge;
        final float leftY = h*0.41f;
        final float dpadX = edge + analog*1.30f;
        final float dpadY = h - step*1.84f;
        final float rightX = w - edge;
        final float rightY = h*0.72f;
        final float faceY = h*0.30f;
        place(LEFT_STICK, leftX, leftY, analog);
        place(RIGHT_STICK, rightX, rightY, analog);
        place(UP, dpadX, dpadY-step, button);
        place(DOWN, dpadX, dpadY+step, button);
        place(LEFT, dpadX-step, dpadY, button);
        place(RIGHT, dpadX+step, dpadY, button);
        place(X, rightX, faceY-step, button);
        place(B, rightX, faceY+step, button);
        place(Y, rightX-step, faceY, button);
        place(A, rightX+step, faceY, button);
        final float top = Math.max(button + 6*d, h*0.087f);
        place(L, edge-button*0.28f, top, button*0.82f);
        place(ZL, edge+button*1.55f, top, button*0.82f);
        place(ZR, w-edge-button*1.55f, top, button*0.82f);
        place(R, w-edge+button*0.28f, top, button*0.82f);
        place(L3, leftX+analog*1.17f, leftY+analog*0.78f, button*0.73f);
        place(R3, rightX-analog*1.08f, rightY-analog*0.79f, button*0.73f);
        place(MINUS, w*0.43f, h-button*1.10f, button*0.68f);
        place(PLUS, w*0.57f, h-button*1.10f, button*0.68f);
        ready = true;
    }

    @Override protected void onSizeChanged(int w, int h, int oldW, int oldH) {
        super.onSizeChanged(w, h, oldW, oldH);
        releaseAll();
        positionControls(w, h);
    }

    private void fill(int color) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(color);
    }

    private void outline(float d) {
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1.35f*d);
        paint.setColor(0xB8FFFFFF);
    }

    private void drawButton(Canvas canvas, int i) {
        float r = radius[i];
        rect.set(cx[i]-r, cy[i]-r, cx[i]+r, cy[i]+r);
        fill(held[i]>0 ? 0xB33A85C6 : 0x9A252F40);
        canvas.drawRoundRect(rect, r*0.55f, r*0.55f, paint);
        outline(density);
        canvas.drawRoundRect(rect, r*0.55f, r*0.55f, paint);
        fill(Color.WHITE);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTypeface(android.graphics.Typeface.create(
                "sans-serif-medium", android.graphics.Typeface.BOLD));
        paint.setTextSize((i>=L3 ? 12f : i>=PLUS ? 18f : 15f)*density);
        Paint.FontMetrics fm = paint.getFontMetrics();
        canvas.drawText(LABELS[i], cx[i],
                cy[i]-(fm.ascent+fm.descent)*0.5f, paint);
    }

    private void drawStick(Canvas canvas, int index, int offset) {
        float x = cx[index], y = cy[index], r = radius[index];
        fill(0x8D1E293B);
        canvas.drawCircle(x,y,r,paint);
        outline(density);
        canvas.drawCircle(x,y,r,paint);
        fill(0x4CFFFFFF);
        canvas.drawCircle(x,y,r*0.71f,paint);
        float dx = axes[offset]*r*0.56f;
        float dy = axes[offset+1]*r*0.56f;
        fill((dx!=0 || dy!=0) ? 0xD856ABE0 : 0xC04A5B73);
        canvas.drawCircle(x+dx,y+dy,r*0.38f,paint);
        outline(density);
        canvas.drawCircle(x+dx,y+dy,r*0.38f,paint);
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (!ready) positionControls(getWidth(),getHeight());
        drawStick(canvas, LEFT_STICK, 0);
        drawStick(canvas, RIGHT_STICK, 2);
        for (int i=0; i<BUTTON_COUNT; i++) drawButton(canvas,i);
    }

    private int hit(float x, float y) {
        int best = -1;
        float nearest = Float.MAX_VALUE;
        // Buttons always have priority if their bounds touch an analog ring.
        for (int i=0; i<BUTTON_COUNT; i++) {
            float dx=x-cx[i], dy=y-cy[i], d2=dx*dx+dy*dy;
            float range=radius[i]*1.10f;
            if (d2<=range*range && d2<nearest) { nearest=d2; best=i; }
        }
        if (best>=0) return best;
        for (int i=LEFT_STICK; i<=RIGHT_STICK; i++) {
            float dx=x-cx[i],dy=y-cy[i];
            if (dx*dx+dy*dy<=radius[i]*radius[i]) return i;
        }
        return -1;
    }

    private int hitButton(float x, float y) {
        int result=hit(x,y);
        return result<BUTTON_COUNT ? result : -1;
    }

    private void press(int control) {
        if (control<0 || control>=BUTTON_COUNT) return;
        if (held[control]++==0) SDLActivity.onNativeKeyDown(KEYS[control]);
        invalidate();
    }

    private void release(int control) {
        if (control<0 || control>=BUTTON_COUNT || held[control]<=0) return;
        if (--held[control]==0) SDLActivity.onNativeKeyUp(KEYS[control]);
        invalidate();
    }

    private void sendAxes() {
        try {
            nativeSetTouchAxes(axes[0], axes[1], axes[2], axes[3]);
        } catch (UnsatisfiedLinkError ignored) {
            // Runtime is not loaded until the game starts.
        }
    }

    private void moveStick(int index, float x, float y) {
        int offset = index==LEFT_STICK ? 0 : 2;
        float range = radius[index]*0.72f;
        float dx = (x-cx[index])/range, dy = (y-cy[index])/range;
        float norm = (float)Math.sqrt(dx*dx+dy*dy);
        if (norm>1f) { dx/=norm; dy/=norm; }
        if (norm<0.10f) { dx=0; dy=0; }
        if (axes[offset]!=dx || axes[offset+1]!=dy) {
            axes[offset]=dx;
            axes[offset+1]=dy;
            sendAxes();
            invalidate();
        }
    }

    private void resetStick(int index) {
        int off=index==LEFT_STICK ? 0 : 2;
        if (axes[off]!=0 || axes[off+1]!=0) {
            axes[off]=axes[off+1]=0;
            sendAxes();
            invalidate();
        }
    }

    private void pointerDown(int pointerId, float x, float y) {
        int control=hit(x,y);
        if (control<0) return;
        // A stick belongs to exactly one pointer. Otherwise releasing one
        // finger would incorrectly zero the other finger's analog value.
        if (control>=LEFT_STICK) {
            for (int i=0;i<pointerToControl.size();i++)
                if (pointerToControl.valueAt(i)==control) return;
        }
        pointerToControl.put(pointerId,control);
        if (control>=LEFT_STICK) moveStick(control,x,y);
        else press(control);
    }

    private void pointerMove(int pointerId, float x, float y) {
        int control=pointerToControl.get(pointerId,-1);
        if (control>=LEFT_STICK) {
            moveStick(control,x,y);
        } else if (control>=0) {
            int next=hitButton(x,y);
            if (next!=control) {
                release(control);
                if (next<0) pointerToControl.delete(pointerId);
                else { pointerToControl.put(pointerId,next); press(next); }
            }
        }
    }

    private void pointerUp(int pointerId) {
        int control=pointerToControl.get(pointerId,-1);
        if (control>=LEFT_STICK) resetStick(control);
        else release(control);
        pointerToControl.delete(pointerId);
    }

    public void releaseAll() {
        for (int i=0;i<BUTTON_COUNT;i++) {
            if (held[i]>0) { held[i]=1; release(i); }
        }
        pointerToControl.clear();
        for(int i=0;i<axes.length;i++) axes[i]=0;
        sendAxes();
        invalidate();
    }

    @Override protected void onDetachedFromWindow() {
        releaseAll();
        super.onDetachedFromWindow();
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        int action=e.getActionMasked(), index=e.getActionIndex();
        if (action==MotionEvent.ACTION_CANCEL) {
            releaseAll();
            return true;
        }
        if (action==MotionEvent.ACTION_DOWN || action==MotionEvent.ACTION_POINTER_DOWN) {
            float x=e.getX(index),y=e.getY(index);
            if (action==MotionEvent.ACTION_DOWN && hit(x,y)<0)
                return false; // keep SDL/ImGui touch outside our controller
            pointerDown(e.getPointerId(index),x,y);
        } else if (action==MotionEvent.ACTION_MOVE) {
            for(int i=0;i<e.getPointerCount();i++)
                pointerMove(e.getPointerId(i),e.getX(i),e.getY(i));
        } else if (action==MotionEvent.ACTION_UP || action==MotionEvent.ACTION_POINTER_UP) {
            pointerUp(e.getPointerId(index));
        }
        return true;
    }
}
