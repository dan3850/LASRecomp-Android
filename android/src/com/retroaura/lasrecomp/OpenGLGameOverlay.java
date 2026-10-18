package com.retroaura.lasrecomp;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.opengl.GLES30;
import android.opengl.GLSurfaceView;
import android.opengl.GLUtils;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.view.MotionEvent;
import android.view.PixelCopy;
import android.view.SurfaceView;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * Experimental REAL-GAME framebuffer presentation through GLES 3.0.
 *
 * Zelda's NVN commands, Maxwell shader translation and GPU work still use Vulkan.
 * We capture the Vulkan SDL SurfaceView with Android PixelCopy asynchronously,
 * upload that exact game's visible pixels to GLES, and display them full-screen.
 * This is a slow, opt-in cross-API correctness experiment, not a GLES NVN backend.
 * The original Vulkan SurfaceView stays alive underneath for safe fallback.
 */
final class OpenGLGameOverlay extends GLSurfaceView {
    private static final String TAG = "LASRecomp/GLES";
    private static final int MAX_WIDTH = 960;
    private static final int MAX_HEIGHT = 540;
    private static final long CAPTURE_INTERVAL_MS = 33; // ceiling ~30 copies per second
    private final SurfaceView source;
    private final File telemetry;
    private final HandlerThread worker;
    private final Handler captureHandler;
    private final Object frameLock = new Object();
    private Bitmap readyFrame;
    private Bitmap spareFrame;
    private volatile boolean active;
    private volatile boolean stopped;
    private long captures;
    private long failures;
    private long presented;
    private long lastReportNs;
    private long previousCopies, previousFailures, previousPresented;
    private String driver = "OpenGL not yet initialized";
    private int captureWidth;
    private int captureHeight;

    OpenGLGameOverlay(Context context, SurfaceView sourceSurface) {
        super(context);
        if (sourceSurface == null) throw new IllegalArgumentException("SDL SurfaceView required");
        source = sourceSurface;
        telemetry = new File(context.getFilesDir(), "graphics/gl-overlay.txt");
        // Alpha=0 before the first real game frame -> underlying Vulkan visible.
        setEGLContextClientVersion(3);
        setEGLConfigChooser(8, 8, 8, 8, 0, 0);
        getHolder().setFormat(PixelFormat.TRANSLUCENT);
        // Above SDL's Vulkan SurfaceView, but below Android's touch controls.
        setZOrderMediaOverlay(true);
        setFocusable(false);
        setFocusableInTouchMode(false);
        setRenderer(new FramePresenter());
        setRenderMode(GLSurfaceView.RENDERMODE_WHEN_DIRTY);
        worker = new HandlerThread("LASRecomp-GL-PixelCopy");
        worker.start();
        captureHandler = new Handler(worker.getLooper());
        report("STATUS=starting\nmode=game Vulkan NVN -> PixelCopy -> OpenGL ES 3.0 present\n");
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        // Input goes to the existing SDL/touch controls, never to this view.
        return false;
    }

    @Override public void onResume() {
        super.onResume();
        active = true;
        if (!stopped) captureHandler.postDelayed(captureTask, 150);
    }

    @Override public void onPause() {
        active = false;
        captureHandler.removeCallbacksAndMessages(null);
        super.onPause();
    }

    void shutdown() {
        stopped = true;
        active = false;
        captureHandler.removeCallbacksAndMessages(null);
        worker.quitSafely();
        synchronized (frameLock) {
            if (readyFrame != null) readyFrame.recycle();
            if (spareFrame != null) spareFrame.recycle();
            readyFrame = spareFrame = null;
        }
    }

    private synchronized void report(String message) {
        Log.i(TAG, message.replace('\n', ' '));
        File parent = telemetry.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) return;
        try (FileOutputStream output = new FileOutputStream(telemetry)) {
            output.write(message.getBytes(StandardCharsets.UTF_8));
        } catch (Exception error) {
            Log.w(TAG, "Cannot write GLES status", error);
        }
    }

    private final Runnable captureTask = new Runnable() {
        @Override public void run() {
            if (!active || stopped) return;
            if (!source.getHolder().getSurface().isValid() ||
                source.getWidth() <= 0 || source.getHeight() <= 0) {
                captureHandler.postDelayed(this, 150);
                return;
            }
            int w = source.getWidth(), h = source.getHeight();
            double scale = Math.min(1.0,
                Math.min((double) MAX_WIDTH / w, (double) MAX_HEIGHT / h));
            int cw = Math.max(1, (int) Math.round(w * scale));
            int ch = Math.max(1, (int) Math.round(h * scale));
            final Bitmap target;
            synchronized (frameLock) {
                captureWidth = cw;
                captureHeight = ch;
                if (spareFrame != null &&
                    spareFrame.getWidth() == cw && spareFrame.getHeight() == ch) {
                    target = spareFrame;
                    spareFrame = null;
                } else {
                    if (spareFrame != null) spareFrame.recycle();
                    spareFrame = null;
                    target = Bitmap.createBitmap(cw, ch, Bitmap.Config.ARGB_8888);
                }
            }
            try {
                PixelCopy.request(source, target, result -> {
                    if (result == PixelCopy.SUCCESS && active && !stopped) {
                        synchronized (frameLock) {
                            if (readyFrame != null) {
                                if (spareFrame != null) spareFrame.recycle();
                                spareFrame = readyFrame;
                            }
                            readyFrame = target;
                            captures++;
                        }
                        requestRender(); // GLES uploads and draws the latest Zelda frame.
                    } else {
                        synchronized (frameLock) {
                            if (spareFrame != null) spareFrame.recycle();
                            spareFrame = target;
                            failures++;
                        }
                        if (failures == 1 || failures % 60 == 0)
                            Log.w(TAG, "PixelCopy failed: " + result);
                    }
                    if (active && !stopped)
                        captureHandler.postDelayed(captureTask, CAPTURE_INTERVAL_MS);
                }, captureHandler);
            } catch (RuntimeException error) {
                synchronized (frameLock) {
                    if (spareFrame != null) spareFrame.recycle();
                    spareFrame = target;
                    failures++;
                }
                if (failures == 1 || failures % 60 == 0)
                    Log.w(TAG, "PixelCopy request failed", error);
                if (active && !stopped) captureHandler.postDelayed(this, 150);
            }
        }
    };

    private final class FramePresenter implements GLSurfaceView.Renderer {
        private final String vertex =
            "#version 300 es\n" +
            "out vec2 uv;\n" +
            "void main() {\n" +
            "  vec2 p = vec2(gl_VertexID == 1 ? 3.0 : -1.0, gl_VertexID == 2 ? 3.0 : -1.0);\n" +
            "  uv = 0.5 * (p + 1.0);\n" +
            "  gl_Position = vec4(p, 0.0, 1.0);\n" +
            "}\n";
        private final String fragment =
            "#version 300 es\n" +
            "precision mediump float;\n" +
            "in vec2 uv;\n" +
            "uniform sampler2D frameTex;\n" +
            "out vec4 outColor;\n" +
            "void main() {\n" +
            "  outColor = vec4(texture(frameTex, vec2(uv.x, 1.0 - uv.y)).rgb, 1.0);\n" +
            "}\n";
        private int program;
        private int tex;
        private int textureWidth;
        private int textureHeight;
        private boolean hasFrame;

        private int shader(int type, String source) {
            int object = GLES30.glCreateShader(type);
            GLES30.glShaderSource(object, source);
            GLES30.glCompileShader(object);
            int[] status = new int[1];
            GLES30.glGetShaderiv(object, GLES30.GL_COMPILE_STATUS, status, 0);
            if (status[0] == 0) {
                String error = GLES30.glGetShaderInfoLog(object);
                GLES30.glDeleteShader(object);
                throw new IllegalStateException("GL shader: " + error);
            }
            return object;
        }

        @Override public void onSurfaceCreated(GL10 unused, EGLConfig config) {
            program = tex = 0;
            hasFrame = false;
            try {
                driver = "GL_VENDOR=" + GLES30.glGetString(GLES30.GL_VENDOR) +
                    "\nGL_RENDERER=" + GLES30.glGetString(GLES30.GL_RENDERER) +
                    "\nGL_VERSION=" + GLES30.glGetString(GLES30.GL_VERSION);
                int v = shader(GLES30.GL_VERTEX_SHADER, vertex);
                int f = shader(GLES30.GL_FRAGMENT_SHADER, fragment);
                int p = GLES30.glCreateProgram();
                GLES30.glAttachShader(p, v);
                GLES30.glAttachShader(p, f);
                GLES30.glLinkProgram(p);
                int[] linked = new int[1];
                GLES30.glGetProgramiv(p, GLES30.GL_LINK_STATUS, linked, 0);
                String errors = GLES30.glGetProgramInfoLog(p);
                GLES30.glDeleteShader(v);
                GLES30.glDeleteShader(f);
                if (linked[0] == 0) {
                    GLES30.glDeleteProgram(p);
                    throw new IllegalStateException("GL link: " + errors);
                }
                program = p;
                lastReportNs = System.nanoTime();
                previousCopies = previousFailures = previousPresented = 0;
                int[] textureIds = new int[1];
                GLES30.glGenTextures(1, textureIds, 0);
                tex = textureIds[0];
                if (tex == 0) throw new IllegalStateException("glGenTextures returned 0");
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, tex);
                GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MIN_FILTER, GLES30.GL_LINEAR);
                GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MAG_FILTER, GLES30.GL_LINEAR);
                GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_S, GLES30.GL_CLAMP_TO_EDGE);
                GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_T, GLES30.GL_CLAMP_TO_EDGE);
                GLES30.glUseProgram(program);
                GLES30.glUniform1i(GLES30.glGetUniformLocation(program, "frameTex"), 0);
                GLES30.glDisable(GLES30.GL_BLEND);
                report("STATUS=ready\nmode=Vulkan NVN + actual Zelda image via OpenGL ES\n" + driver + "\n");
                requestRender();
            } catch (RuntimeException error) {
                Log.e(TAG, "GLES presentation unavailable; leaving original Vulkan visible", error);
                report("STATUS=failed\nmode=Vulkan + GLES framebuffer presentation\n" +
                    driver + "\nreason=" + error.getMessage() + "\n");
            }
        }

        @Override public void onSurfaceChanged(GL10 unused, int w, int h) {
            GLES30.glViewport(0, 0, w, h);
        }

        @Override public void onDrawFrame(GL10 unused) {
            GLES30.glClearColor(0f, 0f, 0f, 0f);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            if (program == 0 || tex == 0) return;
            Bitmap frame;
            synchronized (frameLock) {
                frame = readyFrame;
                readyFrame = null;
            }
            if (frame != null) {
                GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, tex);
                if (textureWidth != frame.getWidth() || textureHeight != frame.getHeight()) {
                    GLUtils.texImage2D(GLES30.GL_TEXTURE_2D, 0, frame, 0);
                    textureWidth = frame.getWidth();
                    textureHeight = frame.getHeight();
                } else {
                    GLUtils.texSubImage2D(GLES30.GL_TEXTURE_2D, 0, 0, 0, frame);
                }
                hasFrame = true;
                synchronized (frameLock) {
                    if (spareFrame != null) spareFrame.recycle();
                    spareFrame = frame;
                    presented++;
                }
            }
            if (hasFrame) {
                GLES30.glUseProgram(program);
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, tex);
                GLES30.glDrawArrays(GLES30.GL_TRIANGLES, 0, 3);
            }
            long now = System.nanoTime();
            if (now - lastReportNs >= 2_000_000_000L) {
                double seconds = (now - lastReportNs) / 1.0e9;
                lastReportNs = now;
                long copied, failed, shown;
                int w, h;
                synchronized (frameLock) {
                    copied = captures;
                    failed = failures;
                    shown = presented;
                    w = captureWidth;
                    h = captureHeight;
                }
                double copyFps = (copied - previousCopies) / seconds;
                double uploadFps = (shown - previousPresented) / seconds;
                long failuresPeriod = failed - previousFailures;
                previousCopies = copied;
                previousFailures = failed;
                previousPresented = shown;
                report(String.format(Locale.US,
                    "STATUS=%s\nmode=Vulkan NVN -> PixelCopy -> GLES full-screen Zelda image\n%s\n" +
                    "pixelCopySuccessTotal=%d\npixelCopyFailureTotal=%d\nglFramesUploadedTotal=%d\n" +
                    "copyRate=%.1f fps\nOpenGL uploadRate=%.1f fps\n" +
                    "pixelCopyFailuresInWindow=%d\ncopySize=%dx%d\n" +
                    "NVN shader and draw commands still run on Vulkan.\n",
                    hasFrame ? "presenting-game" : "waiting-for-game",
                    driver, copied, failed, shown, copyFps, uploadFps, failuresPeriod, w, h));
            }
        }
    }
}
