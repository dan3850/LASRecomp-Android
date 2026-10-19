package com.retroaura.lasrecomp;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.Log;
import android.util.SparseIntArray;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import org.libsdl.app.SDLActivity;

/**
 * Native Android Switch-style touch controls, informed by the layout and
 * independent D-pad/stick/L3/R3 behavior of KenjinxAndroid (Ryujinx Neo).
 * See third_party/kenjinx-android/LICENSE.txt for the MIT attribution.
 *
 * The analogs send actual signed 16-bit axes to the LASRecomp nn::hid runtime.
 * Buttons use the same SDL keyboard bindings as before. UI input never
 * touches Vulkan, the game clock, or audio.
 */
public final class GameTouchControls extends View {
    private static final String TAG = "LASRecompTouch";
    private static final int DP_UP=0, DP_DOWN=1, DP_LEFT=2, DP_RIGHT=3;
    private static final int A=4, B=5, X=6, Y=7, L=8, R=9;
    private static final int ZL=10, ZR=11, PLUS=12, MINUS=13, L3=14, R3=15;
    private static final int LEFT_STICK=16, RIGHT_STICK=17, DPAD=18;
    private static final int BUTTON_COUNT=16;
    private static final String[] LABELS = {
        "▲","▼","◀","▶", "A","B","X","Y",
        "L","R","ZL","ZR","+","−","L3","R3"
    };
    // The left/right sticks now use true analog axes. Arrows are exclusively
    // the independent D-pad. F / numpad 0 are the native default L3/R3 keys.
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
    // Positive Y is UP, matching nn::hid rather than Android screen pixels.
    private static native void nativeSetTouchStick(int stick, int x, int y);
    private static boolean nativeAxisWarning;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float[] cx = new float[BUTTON_COUNT], cy = new float[BUTTON_COUNT];
    private final float[] radius = new float[BUTTON_COUNT];
    private final int[] held = new int[BUTTON_COUNT];
    private final SparseIntArray pointers = new SparseIntArray();
    private final float[] stickX = new float[2], stickY = new float[2];
    private final float[] knobX = new float[2], knobY = new float[2];
    private final float[] stickRadius = new float[2];
    private final int[] lastAxisX = new int[2], lastAxisY = new int[2];
    private int leftOwner=-1, rightOwner=-1, dpadOwner=-1;
    private float dpadX, dpadY, dpadStep;
    private final float density;
    private boolean ready;

    public GameTouchControls(Context context) {
        super(context);
        density = getResources().getDisplayMetrics().density;
        setClickable(true);
        setFocusable(false);
        setWillNotDraw(false);
    }

    private void put(int i, float x, float y, float r) {
        cx[i]=x; cy[i]=y; radius[i]=r;
    }

    private void positionButtons(int width, int height) {
        if (width <= 0 || height <= 0) { ready=false; return; }
        // Neo-like two-handed grouping: left stick / D-pad, right stick / ABXY.
        // All positions are recomputed for landscape resolution and DPI.
        float d=density;
        float r=Math.max(21*d, Math.min(32*d, height*0.063f));
        float sr=Math.min(r*1.7f, height*0.14f);
        float leftX=Math.max(sr+8*d, width*0.125f);
        float faceX=width-leftX;
        float y=height*0.70f;
        float gap=Math.max(sr*2.55f, width*0.155f);
        float dx=leftX+gap;
        float rightX=faceX-gap;

        stickX[0]=leftX; stickY[0]=y;
        stickX[1]=rightX; stickY[1]=y;
        stickRadius[0]=stickRadius[1]=sr;
        knobX[0]=leftX; knobY[0]=y;
        knobX[1]=rightX; knobY[1]=y;
        dpadX=dx; dpadY=y; dpadStep=r*1.09f;
        float dr=r*0.70f;
        put(DP_UP,dx,y-dpadStep,dr);
        put(DP_DOWN,dx,y+dpadStep,dr);
        put(DP_LEFT,dx-dpadStep,y,dr);
        put(DP_RIGHT,dx+dpadStep,y,dr);

        float faceStep=r*1.10f;
        put(X,faceX,y-faceStep,r*0.81f);
        put(B,faceX,y+faceStep,r*0.81f);
        put(Y,faceX-faceStep,y,r*0.81f);
        put(A,faceX+faceStep,y,r*0.81f);

        float top=Math.max(r+8*d,height*0.11f);
        put(L,leftX-r*0.60f,top,r*0.82f);
        put(ZL,leftX+r*1.25f,top,r*0.82f);
        put(ZR,faceX-r*1.25f,top,r*0.82f);
        put(R,faceX+r*0.60f,top,r*0.82f);

        float bottom=height-r*0.88f;
        put(MINUS,width*0.47f,bottom,r*0.68f);
        put(PLUS,width*0.53f,bottom,r*0.68f);
        float stickClickY=Math.min(height-r*0.59f,y+sr+r*0.72f);
        put(L3,leftX,stickClickY,r*0.53f);
        put(R3,rightX,stickClickY,r*0.53f);
        ready=true;
    }

    @Override protected void onSizeChanged(int w,int h,int oldW,int oldH) {
        super.onSizeChanged(w,h,oldW,oldH);
        releaseAll();
        positionButtons(w,h);
    }

    private void circularButton(Canvas canvas, int i) {
        float r=radius[i];
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(held[i]!=0 ? 0xB14596D2 : 0x89303B4A);
        canvas.drawCircle(cx[i],cy[i],r,paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(1.3f*density,r*0.035f));
        paint.setColor(held[i]!=0 ? 0xFFD6EEFF : 0xAAE0E9F4);
        canvas.drawCircle(cx[i],cy[i],r,paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.WHITE);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium",
                android.graphics.Typeface.BOLD));
        paint.setTextSize((i==L3||i==R3?13:i==PLUS||i==MINUS?20:16)*density);
        Paint.FontMetrics fm=paint.getFontMetrics();
        canvas.drawText(LABELS[i],cx[i],cy[i]-(fm.ascent+fm.descent)/2,paint);
    }

    private void drawStick(Canvas canvas,int stick) {
        float x=stickX[stick], y=stickY[stick], r=stickRadius[stick];
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x7C253241);
        canvas.drawCircle(x,y,r,paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(1.3f*density,r*0.025f));
        paint.setColor(0xB8D1DFEE);
        canvas.drawCircle(x,y,r,paint);
        paint.setColor(0x738EA4B9);
        canvas.drawCircle(x,y,r*0.65f,paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0xCC536C88);
        canvas.drawCircle(knobX[stick],knobY[stick],r*0.49f,paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(density,r*0.025f));
        paint.setColor(0xFFE2EAF4);
        canvas.drawCircle(knobX[stick],knobY[stick],r*0.49f,paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(13*density);
        paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium",1));
        paint.setColor(Color.WHITE);
        canvas.drawText(stick==0?"L":"R",knobX[stick],knobY[stick]+5*density,paint);
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (!ready) positionButtons(getWidth(),getHeight());
        if (!ready) return;
        drawStick(canvas,0);
        drawStick(canvas,1);
        // A cross drawn as four discrete tactile sectors; one finger can
        // slide through center or diagonally without dropping other buttons.
        for(int i=0;i<BUTTON_COUNT;i++) circularButton(canvas,i);
    }

    private int hit(float x,float y) {
        // Separate buttons (including L3/R3) always win at their own centers.
        for(int i=A;i<BUTTON_COUNT;i++) {
            float xx=x-cx[i], yy=y-cy[i], reach=radius[i]*1.18f;
            if(xx*xx+yy*yy<=reach*reach)return i;
        }
        for(int i=0;i<2;i++) {
            float xx=x-stickX[i], yy=y-stickY[i], reach=stickRadius[i]*1.12f;
            if(xx*xx+yy*yy<=reach*reach)return i==0?LEFT_STICK:RIGHT_STICK;
        }
        float xx=x-dpadX, yy=y-dpadY;
        float reach=dpadStep*1.55f;
        if(xx*xx+yy*yy<=reach*reach)return DPAD;
        return -1;
    }

    private void key(int i,boolean down) {
        if(down) {
            if(held[i]++==0) SDLActivity.onNativeKeyDown(KEYS[i]);
        } else if(held[i]>0 && --held[i]==0) {
            SDLActivity.onNativeKeyUp(KEYS[i]);
        }
    }

    private void dpadAt(float x,float y) {
        float dx=x-dpadX, dy=y-dpadY;
        float dead=dpadStep*0.31f;
        boolean up=dy < -dead, down=dy > dead;
        boolean left=dx < -dead, right=dx > dead;
        setDirectional(DP_UP,up);
        setDirectional(DP_DOWN,down);
        setDirectional(DP_LEFT,left);
        setDirectional(DP_RIGHT,right);
    }

    private void setDirectional(int i,boolean down) {
        if(down && held[i]==0)key(i,true);
        if(!down && held[i]!=0)key(i,false);
    }

    private void sendStick(int stick,int x,int y) {
        if(lastAxisX[stick]==x && lastAxisY[stick]==y)return;
        lastAxisX[stick]=x; lastAxisY[stick]=y;
        try {
            nativeSetTouchStick(stick,x,y);
        } catch(UnsatisfiedLinkError error) {
            if(!nativeAxisWarning) {
                nativeAxisWarning=true;
                Log.e(TAG,"The installed APK does not provide native analog controls",error);
            }
        }
    }

    private void stickAt(int stick,float x,float y) {
        float r=stickRadius[stick];
        float dx=(x-stickX[stick])/r, dy=(y-stickY[stick])/r;
        float len=(float)Math.sqrt(dx*dx+dy*dy);
        if(len>1f) { dx/=len;dy/=len;len=1f; }
        knobX[stick]=stickX[stick]+dx*r*0.70f;
        knobY[stick]=stickY[stick]+dy*r*0.70f;
        // A short dead zone prevents jitter; proportional movement after it.
        float magnitude=len<0.10f ? 0f : Math.min(1f,(len-0.10f)/0.90f);
        float inv=len>0 ? magnitude/len : 0;
        sendStick(stick,Math.round(dx*inv*32767f),Math.round(-dy*inv*32767f));
        invalidate();
    }

    private void releaseControl(int control,int pointer) {
        if(control==LEFT_STICK && leftOwner==pointer) {
            leftOwner=-1; knobX[0]=stickX[0];knobY[0]=stickY[0];
            sendStick(0,0,0);
        } else if(control==RIGHT_STICK && rightOwner==pointer) {
            rightOwner=-1;knobX[1]=stickX[1];knobY[1]=stickY[1];
            sendStick(1,0,0);
        } else if(control==DPAD && dpadOwner==pointer) {
            dpadOwner=-1;
            for(int i=0;i<4;i++)setDirectional(i,false);
        } else if(control>=A && control<BUTTON_COUNT)key(control,false);
    }

    private void pointerDown(int id,float x,float y) {
        int control=hit(x,y);
        if(control==LEFT_STICK) {
            if(leftOwner!=-1)return;
            leftOwner=id;stickAt(0,x,y);
        } else if(control==RIGHT_STICK) {
            if(rightOwner!=-1)return;
            rightOwner=id;stickAt(1,x,y);
        } else if(control==DPAD) {
            if(dpadOwner!=-1)return;
            dpadOwner=id;dpadAt(x,y);
        } else if(control>=A && control<BUTTON_COUNT) {
            key(control,true);
        } else return;
        pointers.put(id,control);
        invalidate();
    }

    private void pointerMove(int id,float x,float y) {
        int control=pointers.get(id,-1);
        if(control==LEFT_STICK)stickAt(0,x,y);
        else if(control==RIGHT_STICK)stickAt(1,x,y);
        else if(control==DPAD)dpadAt(x,y);
        else if(control>=A && control<BUTTON_COUNT) {
            int next=hit(x,y);
            // Dragging between buttons remains supported; analog and D-pad
            // capture must start with a new touch to prevent spurious motion.
            if(next==control)return;
            releaseControl(control,id);
            pointers.delete(id);
            if(next>=A && next<BUTTON_COUNT) {
                key(next,true);
                pointers.put(id,next);
            }
        } else if(control<0) {
            // A finger that briefly left a button may re-enter it before UP.
            int next=hit(x,y);
            if(next>=A && next<BUTTON_COUNT) {
                key(next,true);
                pointers.put(id,next);
            }
        }
        invalidate();
    }

    private void pointerUp(int id) {
        int control=pointers.get(id,-1);
        if(control>=0)releaseControl(control,id);
        pointers.delete(id);
        invalidate();
    }

    public void releaseAll() {
        for(int i=0;i<held.length;i++) {
            if(held[i]>0) {
                held[i]=1;
                key(i,false);
            }
        }
        pointers.clear();
        leftOwner=rightOwner=dpadOwner=-1;
        for(int i=0;i<2;i++) {
            knobX[i]=stickX[i];knobY[i]=stickY[i];
            sendStick(i,0,0);
        }
        invalidate();
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        int action=e.getActionMasked();
        int index=e.getActionIndex();
        if(action==MotionEvent.ACTION_CANCEL) {
            releaseAll();
            return true;
        }
        if(action==MotionEvent.ACTION_DOWN||action==MotionEvent.ACTION_POINTER_DOWN) {
            int id=e.getPointerId(index);
            if(action==MotionEvent.ACTION_DOWN && hit(e.getX(index),e.getY(index))<0)
                return false; // Empty areas still belong to the SDL surface.
            pointerDown(id,e.getX(index),e.getY(index));
        } else if(action==MotionEvent.ACTION_MOVE) {
            for(int i=0;i<e.getPointerCount();i++)
                pointerMove(e.getPointerId(i),e.getX(i),e.getY(i));
        } else if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_POINTER_UP) {
            pointerUp(e.getPointerId(index));
        }
        return true;
    }
}
