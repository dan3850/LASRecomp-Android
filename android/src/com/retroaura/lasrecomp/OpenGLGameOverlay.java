package com.retroaura.lasrecomp;

import android.content.Context;
import android.graphics.PixelFormat;
import android.opengl.GLES30;
import android.opengl.GLSurfaceView;
import android.util.Log;
import android.view.MotionEvent;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * OpenGL ES game-coexistence probe, NOT a second NVN backend.
 *
 * The underlying SDL game surface remains Vulkan. A separate, transparent
 * GLES 3.0 SurfaceView draws a small shader-animated triangle above Zelda.
 * This verifies EGL/GLES + Vulkan coexistence, GL shader execution, lifecycle
 * and presentation while Zelda executes. It does not render any NVN commands.
 */
final class OpenGLGameOverlay extends GLSurfaceView {
    private static final String TAG = "LASRecomp/GLES";
    private final File telemetry;

    OpenGLGameOverlay(Context context) {
        super(context);
        telemetry = new File(context.getFilesDir(), "graphics/gl-overlay.txt");
        // Independent EGL context; no Vulkan/GLES resource sharing assumed.
        setEGLContextClientVersion(3);
        setEGLConfigChooser(8, 8, 8, 8, 16, 0);
        getHolder().setFormat(PixelFormat.TRANSLUCENT);
        setZOrderOnTop(true);
        setFocusable(false);
        setFocusableInTouchMode(false);
        setRenderer(new ProbeRenderer());
        setRenderMode(GLSurfaceView.RENDERMODE_CONTINUOUSLY);
    }

    // Do not consume the SDL game controls' touches.
    @Override public boolean onTouchEvent(MotionEvent event) { return false; }

    private synchronized void report(String text) {
        Log.i(TAG, text.replace('\n', ' '));
        File parent = telemetry.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) return;
        try (FileOutputStream out = new FileOutputStream(telemetry)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        } catch (Exception error) {
            Log.w(TAG, "Cannot write GLES diagnostics", error);
        }
    }

    private final class ProbeRenderer implements GLSurfaceView.Renderer {
        private final String vertex =
            "#version 300 es\n" +
            "uniform float uTime;\n" +
            "void main() {\n" +
            "  vec2 p[3] = vec2[3](vec2(-0.97, 0.72), vec2(-0.78, 0.72), vec2(-0.875, 0.97));\n" +
            "  gl_Position = vec4(p[gl_VertexID] + vec2(0.0, sin(uTime * 3.0) * 0.015), 0.0, 1.0);\n" +
            "}\n";
        private final String fragment =
            "#version 300 es\n" +
            "precision highp float;\n" +
            "uniform float uTime;\n" +
            "out vec4 outColor;\n" +
            "void main() {\n" +
            "  float pulse = 0.5 + 0.5 * sin(uTime * 4.0);\n" +
            "  outColor = vec4(0.15 + pulse * 0.5, 0.9, 0.35, 0.82);\n" +
            "}\n";
        private int program;
        private int timeUniform;
        private long startedNs;
        private long fpsStartNs;
        private int frames;
        private String deviceInfo = "Not initialized";

        private int compile(int stage, String source) {
            int s = GLES30.glCreateShader(stage);
            GLES30.glShaderSource(s, source);
            GLES30.glCompileShader(s);
            int[] status = new int[1];
            GLES30.glGetShaderiv(s, GLES30.GL_COMPILE_STATUS, status, 0);
            if (status[0] == 0) {
                String msg = GLES30.glGetShaderInfoLog(s);
                GLES30.glDeleteShader(s);
                throw new IllegalStateException("Shader compile failed: " + msg);
            }
            return s;
        }

        @Override public void onSurfaceCreated(GL10 unused, EGLConfig config) {
            program = 0;
            try {
                deviceInfo = "OpenGL vendor=" + GLES30.glGetString(GLES30.GL_VENDOR) +
                    "\nOpenGL renderer=" + GLES30.glGetString(GLES30.GL_RENDERER) +
                    "\nOpenGL version=" + GLES30.glGetString(GLES30.GL_VERSION);
                int vs = compile(GLES30.GL_VERTEX_SHADER, vertex);
                int fs = compile(GLES30.GL_FRAGMENT_SHADER, fragment);
                int p = GLES30.glCreateProgram();
                GLES30.glAttachShader(p, vs);
                GLES30.glAttachShader(p, fs);
                GLES30.glLinkProgram(p);
                int[] linked = new int[1];
                GLES30.glGetProgramiv(p, GLES30.GL_LINK_STATUS, linked, 0);
                String error = GLES30.glGetProgramInfoLog(p);
                GLES30.glDeleteShader(vs);
                GLES30.glDeleteShader(fs);
                if (linked[0] == 0) {
                    GLES30.glDeleteProgram(p);
                    throw new IllegalStateException("Program link failed: " + error);
                }
                program = p;
                timeUniform = GLES30.glGetUniformLocation(program, "uTime");
                GLES30.glDisable(GLES30.GL_DEPTH_TEST);
                GLES30.glEnable(GLES30.GL_BLEND);
                GLES30.glBlendFunc(GLES30.GL_SRC_ALPHA, GLES30.GL_ONE_MINUS_SRC_ALPHA);
                startedNs = fpsStartNs = System.nanoTime();
                frames = 0;
                report("STATUS=running\nmode=Vulkan game + independent OpenGL ES overlay\n"
                    + deviceInfo + "\nThe Zelda NVN backend is still Vulkan.\n");
            } catch (RuntimeException error) {
                report("STATUS=failed\nmode=Vulkan game + OpenGL ES overlay\n" +
                    deviceInfo + "\nreason=" + error.getMessage() + "\n");
                Log.e(TAG, "GLES overlay setup failed", error);
            }
        }

        @Override public void onSurfaceChanged(GL10 unused, int width, int height) {
            GLES30.glViewport(0, 0, Math.max(1, width), Math.max(1, height));
        }

        @Override public void onDrawFrame(GL10 unused) {
            GLES30.glClearColor(0f, 0f, 0f, 0f);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            if (program == 0) return;
            long now = System.nanoTime();
            GLES30.glUseProgram(program);
            GLES30.glUniform1f(timeUniform, (now - startedNs) / 1.0e9f);
            GLES30.glDrawArrays(GLES30.GL_TRIANGLES, 0, 3);
            frames++;
            if (now - fpsStartNs >= 2_000_000_000L) {
                double fps = (double) frames * 1.0e9 / (now - fpsStartNs);
                report(String.format(Locale.US,
                    "STATUS=running\nmode=Vulkan game + OpenGL ES overlay\n%s\n" +
                    "OpenGL overlay frames/s=%.1f\n" +
                    "This does not measure game FPS. NVN game renderer=Vulkan.\n",
                    deviceInfo, fps));
                fpsStartNs = now;
                frames = 0;
            }
        }
    }
}
