package org.scarletnx;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.PrintWriter;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import android.util.Base64;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Pure-Java launcher: never loads SDL or libmain.so before showing diagnostics. */
public final class DiagnosticActivity extends Activity {
    private TextView report;
    private String log;
    private static final int SAVE_LOG_REQUEST = 4301;
    private static final String PREF = "startup_diagnostic";
    private static final String PENDING = "launch_pending";
    private static final int MAX_TOMBSTONE_BYTES = 1048576;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            StringWriter sw = new StringWriter();
            error.printStackTrace(new PrintWriter(sw));
            getSharedPreferences(PREF, MODE_PRIVATE).edit()
                .putString("last_java_crash", sw.toString()).commit();
            android.os.Process.killProcess(android.os.Process.myPid());
        });
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(16 * getResources().getDisplayMetrics().density);
        panel.setPadding(pad, pad, pad, pad);
        TextView title = new TextView(this);
        title.setText("ScarletNX - Diagnostico de inicializacao");
        title.setTextSize(21);
        panel.addView(title);
        Button start = new Button(this);
        start.setText("Iniciar ScarletNX");
        panel.addView(start);
        Button copy = new Button(this);
        copy.setText("Copiar log");
        panel.addView(copy);
        Button save = new Button(this);
        save.setText("Salvar log TXT");
        panel.addView(save);
        Button refresh = new Button(this);
        refresh.setText("Atualizar diagnostico");
        panel.addView(refresh);
        ScrollView scroll = new ScrollView(this);
        report = new TextView(this);
        report.setTextIsSelectable(true);
        scroll.addView(report);
        panel.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(panel);
        refresh();
        start.setOnClickListener(v -> {
            getSharedPreferences(PREF, MODE_PRIVATE).edit()
                .putBoolean(PENDING, true)
                .putLong("launch_time", System.currentTimeMillis()).commit();
            try { startActivity(new Intent(this, MainActivity.class)); }
            catch (Throwable t) {
                getSharedPreferences(PREF, MODE_PRIVATE).edit()
                    .putString("last_java_crash", android.util.Log.getStackTraceString(t)).commit();
                refresh();
            }
        });
        copy.setOnClickListener(v -> {
            ((ClipboardManager)getSystemService(CLIPBOARD_SERVICE))
                .setPrimaryClip(ClipData.newPlainText("ScarletNX diagnostic", log));
            android.widget.Toast.makeText(this, "Log copiado", android.widget.Toast.LENGTH_SHORT).show();
        });
        save.setOnClickListener(v -> {
            refresh();
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("text/plain");
            intent.putExtra(Intent.EXTRA_TITLE, "ScarletNX-diagnostico-" +
                new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date()) + ".txt");
            startActivityForResult(intent, SAVE_LOG_REQUEST);
        });
        refresh.setOnClickListener(v -> refresh());
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != SAVE_LOG_REQUEST || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        try (OutputStream out = getContentResolver().openOutputStream(data.getData())) {
            if (out == null) throw new java.io.IOException("Destino indisponivel");
            out.write(log.getBytes(StandardCharsets.UTF_8));
            android.widget.Toast.makeText(this, "Log TXT salvo", android.widget.Toast.LENGTH_LONG).show();
        } catch (Exception error) {
            android.widget.Toast.makeText(this, "Erro ao salvar TXT: " + error.getMessage(), android.widget.Toast.LENGTH_LONG).show();
        }
    }

    @Override protected void onResume() {
        super.onResume();
        if (report != null) refresh();
    }

    private void refresh() {
        StringBuilder sb = new StringBuilder();
        sb.append("Android SDK: ").append(Build.VERSION.SDK_INT)
          .append("\nDispositivo: ").append(Build.MANUFACTURER).append(" ").append(Build.MODEL)
          .append("\nAplicativo: ").append(getPackageName()).append("\n");
        android.content.SharedPreferences p = getSharedPreferences(PREF, MODE_PRIVATE);
        sb.append("Ultima tentativa: ");
        long when = p.getLong("launch_time", 0);
        sb.append(when == 0 ? "nenhuma" : new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date(when)));
        sb.append("\nInicio solicitado: ").append(p.getBoolean(PENDING, false)).append("\n");
        sb.append("\nFalha Java registrada:\n").append(p.getString("last_java_crash", "nenhuma")).append("\n");
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                ActivityManager am = (ActivityManager)getSystemService(ACTIVITY_SERVICE);
                List<ApplicationExitInfo> exits = am.getHistoricalProcessExitReasons(null, 0, 8);
                sb.append("\nHistorico de encerramentos Android:\n");
                int traces = 0;
                for (ApplicationExitInfo e : exits) {
                    sb.append("Processo: ").append(e.getProcessName())
                      .append(" | motivo: ").append(e.getReason())
                      .append(" | status: ").append(e.getStatus())
                      .append(" | hora: ").append(new Date(e.getTimestamp()))
                      .append(" | descricao: ").append(e.getDescription()).append("\n");
                    if (e.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE && traces++ < 2) {
                        try (InputStream stream = e.getTraceInputStream()) {
                            if (stream == null) { sb.append("Tombstone: Android nao disponibilizou\n"); continue; }
                            ByteArrayOutputStream out = new ByteArrayOutputStream();
                            byte[] buf = new byte[4096];
                            int n;
                            while (out.size() < MAX_TOMBSTONE_BYTES && (n = stream.read(buf, 0, Math.min(buf.length, MAX_TOMBSTONE_BYTES - out.size()))) > 0) out.write(buf, 0, n);
                            byte[] raw = out.toByteArray();
                            sb.append("Tombstone bruto (Base64, ate 1 MiB; pode ser protobuf):\n")
                              .append(Base64.encodeToString(raw, Base64.NO_WRAP)).append("\n");
                        } catch (Exception err) { sb.append("Tombstone indisponivel: ").append(err).append("\n"); }
                    }
                }
            } catch (Exception e) { sb.append("\nHistorico indisponivel: ").append(e).append("\n"); }
        }
        log = sb.toString();
        int first = log.indexOf("Tombstone bruto");
        report.setText(first < 0 ? log : log.substring(0, first) + "\nTombstone coletado. Use Copiar log para exportar o diagnostico completo (" + log.length() + " caracteres).\n");
    }
}
