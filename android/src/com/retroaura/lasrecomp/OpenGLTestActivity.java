package com.retroaura.lasrecomp;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.opengl.GLES30;
import android.opengl.GLSurfaceView;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.TextView;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * Independent OpenGL ES 3.0 driver smoke test.
 * IMPORTANT: This is NOT the NVN renderer for Zelda. The game still uses Vulkan.
 * Renders shader-driven geometry without Vulkan and reports driver/CPU-side FPS.
 */
public final class OpenGLTestActivity extends Activity {
    private GLSurfaceView view;
    private TextView info;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);

        FrameLayout root = new FrameLayout(this);
        view = new GLSurfaceView(this);
        view.setEGLContextClientVersion(3);
        view.setEGLConfigChooser(8, 8, 8, 8, 24, 8);
        view.setRenderer(new Scene());
        view.setRenderMode(GLSurfaceView.RENDERMODE_CONTINUOUSLY);
        root.addView(view, new FrameLayout.LayoutParams(-1, -1));

        info = new TextView(this);
        info.setTextColor(0xffffffff);
        info.setTextSize(13);
        info.setPadding(20, 12, 20, 12);
        info.setBackgroundColor(0xb9000000);
        info.setText("Inicializando OpenGL ES 3.0...");
        FrameLayout.LayoutParams top = new FrameLayout.LayoutParams(-1, -2, Gravity.TOP);
        root.addView(info, top);

        Button back = new Button(this);
        back.setText("VOLTAR AO MENU");
        back.setOnClickListener(v -> finish());
        FrameLayout.LayoutParams bottom = new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.RIGHT);
        bottom.setMargins(8, 8, 16, 16);
        root.addView(back, bottom);
        setContentView(root);
    }

    @Override public void onPause() {
        if (view != null) view.onPause();
        super.onPause();
    }

    @Override public void onResume() {
        super.onResume();
        if (view != null) view.onResume();
    }

    private void report(String text) {
        runOnUiThread(() -> {
            if (!isFinishing() && info != null) info.setText(text);
        });
    }

    private final class Scene implements GLSurfaceView.Renderer {
        private static final String VERT =
            "#version 300 es\n" +
            "void main() {\n" +
            "  vec2 p = vec2((gl_VertexID == 1) ? 3.0 : -1.0, (gl_VertexID == 2) ? 3.0 : -1.0);\n" +
            "  gl_Position = vec4(p, 0.0, 1.0);\n" +
            "}\n";
        private static final String FRAG =
            "#version 300 es\n" +
            "precision highp float;\n" +
            "uniform vec2 uSize;\n" +
            "uniform float uTime;\n" +
            "out vec4 fragColor;\n" +
            "void main() {\n" +
            "  vec2 p = (gl_FragCoord.xy - 0.5 * uSize) / max(1.0, min(uSize.x, uSize.y));\n" +
            "  float r = length(p);\n" +
            "  float wave = 0.5 + 0.5 * sin(32.0 * r - 2.0 * uTime);\n" +
            "  vec3 base = vec3(0.08, 0.14, 0.25) + vec3(0.15, 0.44, 0.72) * wave;\n" +
            "  base += 0.16 * vec3(sin(uTime + p.x * 8.0), cos(uTime + p.y * 8.0), sin(uTime));\n" +
            "  fragColor = vec4(clamp(base, 0.0, 1.0), 1.0);\n" +
            "}\n";

        private int program, resolution, time;
        private int width = 1, height = 1, frames;
        private long started, statsAt;
        private String driver = "";

        private int shader(int kind, String code) {
            int s = GLES30.glCreateShader(kind);
            GLES30.glShaderSource(s, code);
            GLES30.glCompileShader(s);
            int[] ok = new int[1];
            GLES30.glGetShaderiv(s, GLES30.GL_COMPILE_STATUS, ok, 0);
            if (ok[0] == 0) {
                String error = GLES30.glGetShaderInfoLog(s);
                GLES30.glDeleteShader(s);
                throw new IllegalStateException("OpenGL shader error: " + error);
            }
            return s;
        }

        @Override public void onSurfaceCreated(GL10 unused, EGLConfig config) {
            try {
                driver = "GPU: " + GLES30.glGetString(GLES30.GL_RENDERER) +
                    "\nFabricante: " + GLES30.glGetString(GLES30.GL_VENDOR) +
                    "\nAPI: " + GLES30.glGetString(GLES30.GL_VERSION);
                int vs = shader(GLES30.GL_VERTEX_SHADER, VERT);
                int fs = shader(GLES30.GL_FRAGMENT_SHADER, FRAG);
                program = GLES30.glCreateProgram();
                GLES30.glAttachShader(program, vs);
                GLES30.glAttachShader(program, fs);
                GLES30.glLinkProgram(program);
                int[] ok = new int[1];
                GLES30.glGetProgramiv(program, GLES30.GL_LINK_STATUS, ok, 0);
                String error = GLES30.glGetProgramInfoLog(program);
                GLES30.glDeleteShader(vs);
                GLES30.glDeleteShader(fs);
                if (ok[0] == 0) throw new IllegalStateException("OpenGL link error: " + error);
                resolution = GLES30.glGetUniformLocation(program, "uSize");
                time = GLES30.glGetUniformLocation(program, "uTime");
                started = statsAt = System.nanoTime();
                frames = 0;
                report("OPENGL ES 3.0 — TESTE INDEPENDENTE (SEM ZELDA)\n" + driver);
            } catch (RuntimeException e) {
                program = 0;
                android.util.Log.e("LASRecomp/GLES", "GLES test failed", e);
                report("Falha no teste OpenGL ES 3.0:\n" + e.getMessage());
            }
        }

        @Override public void onSurfaceChanged(GL10 unused, int w, int h) {
            width = Math.max(1, w);
            height = Math.max(1, h);
            GLES30.glViewport(0, 0, width, height);
        }

        @Override public void onDrawFrame(GL10 unused) {
            GLES30.glClearColor(0.06f, 0.09f, 0.15f, 1.0f);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            if (program == 0) return;
            long now = System.nanoTime();
            GLES30.glUseProgram(program);
            GLES30.glUniform2f(resolution, width, height);
            GLES30.glUniform1f(time, (now - started) / 1.0e9f);
            GLES30.glDrawArrays(GLES30.GL_TRIANGLES, 0, 3);
            frames++;
            if (now - statsAt >= 1000000000L) {
                double fps = frames * 1.0e9 / (now - statsAt);
                String label = String.format(java.util.Locale.US,
                    "OPENGL ES 3.0 — TESTE INDEPENDENTE (SEM ZELDA)\n%s\n" +
                    "Resolução: %d x %d | Frames do teste: %.1f FPS\n" +
                    "Este FPS não mede o desempenho do jogo.", driver, width, height, fps);
                report(label);
                android.util.Log.i("LASRecomp/GLES", label.replace('\n', ' '));
                statsAt = now;
                frames = 0;
            }
        }
    }
}
