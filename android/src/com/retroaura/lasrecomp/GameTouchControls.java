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
 * Lightweight, multi-touch gamepad on top of the official SDL3 surface.
 * Sends real SDL Android keyboard events through SDLActivity, so the existing
 * LASRecomp input bindings (and in-game menus) stay responsible for controls.
 * Never pauses/reroutes Vulkan or the game's frame/audio cadence.
 */
public final class GameTouchControls extends View {
    private static final int UP=0, DOWN=1, LEFT=2, RIGHT=3;
    private static final int A=4, B=5, X=6, Y=7, L=8, R=9;
    private static final int ZL=10, ZR=11, PLUS=12, MINUS=13;
    private static final String[] LABELS = {
        "▲","▼","◀","▶", "A","B","X","Y", "L","R","ZL","ZR","+","−"
    };
    // The left stick uses WASD; double-send arrows for SDL menus/d-pad.
    // Face buttons are the original LASRecomp keyboard defaults.
    private static final int[][] KEYS = {
        {KeyEvent.KEYCODE_W,KeyEvent.KEYCODE_DPAD_UP},
        {KeyEvent.KEYCODE_S,KeyEvent.KEYCODE_DPAD_DOWN},
        {KeyEvent.KEYCODE_A,KeyEvent.KEYCODE_DPAD_LEFT},
        {KeyEvent.KEYCODE_D,KeyEvent.KEYCODE_DPAD_RIGHT},
        {KeyEvent.KEYCODE_K,KeyEvent.KEYCODE_ENTER},
        {KeyEvent.KEYCODE_J},
        {KeyEvent.KEYCODE_L},
        {KeyEvent.KEYCODE_I},
        {KeyEvent.KEYCODE_Q},
        {KeyEvent.KEYCODE_E},
        {KeyEvent.KEYCODE_1},
        {KeyEvent.KEYCODE_3},
        {KeyEvent.KEYCODE_ENTER},
        {KeyEvent.KEYCODE_DEL}
    };
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float[] cx = new float[LABELS.length], cy = new float[LABELS.length];
    private final float[] radius = new float[LABELS.length];
    private final int[] held = new int[LABELS.length];
    private final SparseIntArray pointerToButton = new SparseIntArray();
    private float density;
    private boolean ready;

    public GameTouchControls(Context context) {
        super(context);
        density = getResources().getDisplayMetrics().density;
        setClickable(true);
        setFocusable(false);
        setWillNotDraw(false);
    }

    private void setButton(int i, float x, float y, float r) {
        cx[i]=x; cy[i]=y; radius[i]=r;
    }

    private void positionButtons(int width, int height) {
        // Use dp to preserve familiar touch targets on both phones and tablets.
        float d = density;
        float shortSide = Math.min(width, height);
        float r = Math.max(26*d, Math.min(36*d, shortSide*0.075f));
        float side = Math.min(112*d, width*0.19f);
        float middle = height - Math.min(114*d, height*0.30f);
        float step = r*1.45f;
        setButton(UP,side,middle-step,r);
        setButton(DOWN,side,middle+step,r);
        setButton(LEFT,side-step,middle,r);
        setButton(RIGHT,side+step,middle,r);

        float faceX = width-side;
        float faceY = middle;
        setButton(X,faceX,faceY-step,r);
        setButton(B,faceX,faceY+step,r);
        setButton(Y,faceX-step,faceY,r);
        setButton(A,faceX+step,faceY,r);

        float top = Math.max(r+10*d, height*0.095f);
        setButton(L,side-r,top,r*0.87f);
        setButton(ZL,side+r*1.08f,top,r*0.87f);
        setButton(ZR,width-side-r*1.08f,top,r*0.87f);
        setButton(R,width-side+r,top,r*0.87f);
        setButton(MINUS,width/2-1.05f*step,height-1.25f*r,r*0.75f);
        setButton(PLUS,width/2+1.05f*step,height-1.25f*r,r*0.75f);
        ready=true;
    }
    @Override protected void onSizeChanged(int w,int h,int ow,int oh) {
        super.onSizeChanged(w,h,ow,oh);
        releaseAll();
        positionButtons(w,h);
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (!ready) positionButtons(getWidth(),getHeight());
        for (int i=0; i<LABELS.length; ++i) {
            float r=radius[i];
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(held[i]>0 ? 0xAA2196F3 : 0x67313C4E);
            canvas.drawRoundRect(new RectF(cx[i]-r,cy[i]-r,cx[i]+r,cy[i]+r),r*0.50f,r*0.50f,paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(1.6f*density);
            paint.setColor(0xB8FFFFFF);
            canvas.drawRoundRect(new RectF(cx[i]-r,cy[i]-r,cx[i]+r,cy[i]+r),r*0.50f,r*0.50f,paint);
            paint.setStyle(Paint.Style.FILL);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.BOLD));
            paint.setTextSize((i>=PLUS?20:16)*density);
            paint.setColor(Color.WHITE);
            Paint.FontMetrics fm=paint.getFontMetrics();
            canvas.drawText(LABELS[i],cx[i],cy[i]-(fm.ascent+fm.descent)/2,paint);
        }
    }

    private int hit(float x,float y) {
        int result=-1;
        float distance=Float.MAX_VALUE;
        for(int i=0;i<cx.length;i++) {
            float dx=x-cx[i],dy=y-cy[i],dist=dx*dx+dy*dy;
            float reach=radius[i]*1.18f;
            if(dist<=reach*reach && dist<distance) {result=i;distance=dist;}
        }
        return result;
    }
    private void press(int btn) {
        if(btn<0)return;
        if(held[btn]++==0) {
            for(int code:KEYS[btn]) SDLActivity.onNativeKeyDown(code);
        }
        invalidate();
    }
    private void release(int btn) {
        if(btn<0||held[btn]<=0)return;
        if(--held[btn]==0) {
            for(int code:KEYS[btn]) SDLActivity.onNativeKeyUp(code);
        }
        invalidate();
    }
    private void setPointer(int id,int btn) {
        int old=pointerToButton.get(id,-1);
        if(old==btn)return;
        if(old>=0)release(old);
        if(btn>=0){pointerToButton.put(id,btn);press(btn);}
        else pointerToButton.delete(id);
    }
    public void releaseAll() {
        for(int i=0;i<held.length;i++) {
            if(held[i]>0) {
                held[i]=1;
                release(i);
            }
        }
        pointerToButton.clear();
    }
    @Override public boolean onTouchEvent(MotionEvent e) {
        int action=e.getActionMasked();
        int index=e.getActionIndex();
        if(action==MotionEvent.ACTION_CANCEL) {
            releaseAll();
            return true;
        }
        if(action==MotionEvent.ACTION_DOWN||action==MotionEvent.ACTION_POINTER_DOWN) {
            int button=hit(e.getX(index),e.getY(index));
            if(button<0 && action==MotionEvent.ACTION_DOWN)return false; // SDL handles unoccupied screen
            setPointer(e.getPointerId(index),button);
        } else if(action==MotionEvent.ACTION_MOVE) {
            for(int i=0;i<e.getPointerCount();i++)
                setPointer(e.getPointerId(i),hit(e.getX(i),e.getY(i)));
        } else if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_POINTER_UP) {
            setPointer(e.getPointerId(index),-1);
        }
        return true;
    }
}
