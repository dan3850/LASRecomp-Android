package com.retroaura.lasrecomp;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.os.Build;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.json.JSONObject;

/** Separate Mario test app; uses the existing SDL lifecycle and read-only SAF bridge. */
public final class MarioBootActivity extends Activity {
    private static final int PICK_GAME = 201;
    private static final int SAVE_LOG = 202;
    private TextView status;
    private Button play;
    private Uri selected;
    private boolean checking;

    // A native abort or OOM kill may happen before the user can capture threads.
    // Android preserves the process-exit reason for the NEXT launch of this app.
    private void savePreviousProcessExits() {
        if (Build.VERSION.SDK_INT < 30) return;
        try {
            ActivityManager manager = (ActivityManager) getSystemService(ACTIVITY_SERVICE);
            if (manager == null) return;
            java.util.List<ApplicationExitInfo> history =
                    manager.getHistoricalProcessExitReasons(getPackageName(), 0, 4);
            try (FileOutputStream output = new FileOutputStream(
                    new File(getFilesDir(), "mario-exit.log"), false)) {
                if (history.isEmpty()) {
                    output.write("Nenhum encerramento anterior registrado pelo Android.\n"
                            .getBytes(StandardCharsets.UTF_8));
                }
                for (int i = 0; i < history.size(); i++) {
                    ApplicationExitInfo info = history.get(i);
                    String heading = "exit[" + i + "] timestamp=" + info.getTimestamp()
                            + " reason=" + info.getReason() + " status=" + info.getStatus()
                            + " process=" + info.getProcessName()
                            + " importance=" + info.getImportance()
                            + " description=" + info.getDescription() + "\n";
                    output.write(heading.getBytes(StandardCharsets.UTF_8));
                    if (i != 0) continue;
                    // Bound the Android-provided native tombstone/ANR trace size.
                    try (InputStream trace = info.getTraceInputStream()) {
                        if (trace == null) continue;
                        output.write("--- Android exit trace (max 48 KiB) ---\n"
                                .getBytes(StandardCharsets.UTF_8));
                        byte[] chunk = new byte[4096];
                        int total = 0, n;
                        while (total < 49152 &&
                                (n = trace.read(chunk, 0, Math.min(chunk.length, 49152 - total))) > 0) {
                            output.write(chunk, 0, n);
                            total += n;
                        }
                        output.write("\n--- end Android exit trace ---\n"
                                .getBytes(StandardCharsets.UTF_8));
                    } catch (Exception traceError) {
                        output.write(("trace unavailable: " + traceError + "\n")
                                .getBytes(StandardCharsets.UTF_8));
                    }
                }
            }
        } catch (Exception ignored) {
            // An unavailable Android history API must not block the game.
        }
    }


    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        savePreviousProcessExits();
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int)(20 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);
        TextView title = new TextView(this);
        title.setText("Mario Recomp — teste de inicialização");
        title.setTextSize(23);
        layout.addView(title);
        TextView description = new TextView(this);
        description.setText("Selecione a pasta Super-extraido que contém exefs e romfs. " +
            "O jogo será lido dessa pasta. A biblioteca já está neste APK de teste.");
        layout.addView(description);
        Button folder = new Button(this);
        folder.setText("Selecionar pasta do Mario");
        folder.setOnClickListener(v -> {
            if (checking) return;
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION |
                            Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
            startActivityForResult(intent, PICK_GAME);
        });
        layout.addView(folder);
        play = new Button(this);
        play.setText("Iniciar teste");
        play.setEnabled(false);
        play.setOnClickListener(v -> {
            if (selected == null || checking) return;
            new File(getFilesDir(), "mario-esperas.log").delete();
            new File(getFilesDir(), "mario-threads.log").delete();
            startActivity(new Intent(this, GameSDLActivity.class).putExtra("game_tree_uri", selected.toString())
                .putExtra("mario_thread_capture", true));
        });
        layout.addView(play);
        Button logs = new Button(this);
        logs.setText("Ver último log");
        logs.setOnClickListener(v -> status.setText(readLogs()));
        layout.addView(logs);
        Button save = new Button(this);
        save.setText("Salvar log");
        save.setOnClickListener(v -> startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain")
            .putExtra(Intent.EXTRA_TITLE, "Mario-Recomp-boot.txt"), SAVE_LOG));
        layout.addView(save);
        status = new TextView(this);
        status.setTextIsSelectable(true);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(status);
        layout.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        String saved = getSharedPreferences("mario_boot", MODE_PRIVATE).getString("game_tree", null);
        if (saved != null) validateFolder(Uri.parse(saved));
        else status.setText("Aguardando a pasta do jogo. O primeiro boot ainda está em teste.");
    }

    private JSONObject profile() throws Exception {
        try (InputStream input = getAssets().open("mario_boot_profile.json");
             ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) {
                bytes.write(buffer, 0, count);
                if (bytes.size() > 65536) throw new java.io.IOException("Perfil inválido");
            }
            return new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
        }
    }

    private void checkModule(Uri tree, String name, String expected) throws Exception {
        int fd = GameDocumentBridge.openReadFd(this, tree, "exefs/" + name);
        try (DataInputStream input = new DataInputStream(new ParcelFileDescriptor.AutoCloseInputStream(
                 ParcelFileDescriptor.adoptFd(fd)))) {
            byte[] header = new byte[96];
            input.readFully(header);
            if (header[0] != 'N' || header[1] != 'S' || header[2] != 'O' || header[3] != '0')
                throw new java.io.IOException(name + ": NSO inválido");
            StringBuilder hex = new StringBuilder();
            final char[] digits = "0123456789abcdef".toCharArray();
            for (int i = 64; i < 96; i++) {
                int value = header[i] & 255;
                hex.append(digits[value >>> 4]).append(digits[value & 15]);
            }
            if (!hex.toString().equals(expected))
                throw new java.io.IOException(name + ": versão diferente da biblioteca deste APK");
        }
    }

    private void validateFolder(Uri tree) {
        checking = true;
        selected = null;
        play.setEnabled(false);
        status.setText("Verificando os executáveis e o acesso à pasta…");
        new Thread(() -> {
            try {
                if (!GameDocumentBridge.hasPermission(this, tree))
                    throw new java.io.IOException("Selecione a pasta novamente para conceder acesso permanente");
                JSONObject builds = profile().getJSONObject("build_ids");
                checkModule(tree, "main", builds.getString("main"));
                checkModule(tree, "sdk", builds.getString("sdk"));
                GameDocumentBridge.child(this, tree, "romfs");
                int fd = GameDocumentBridge.openReadFd(this, tree, "exefs/main.npdm");
                try (DataInputStream input = new DataInputStream(new ParcelFileDescriptor.AutoCloseInputStream(
                         ParcelFileDescriptor.adoptFd(fd)))) {
                    byte[] magic = new byte[4];
                    input.readFully(magic);
                    if (!Arrays.equals(magic, new byte[]{'M','E','T','A'}))
                        throw new java.io.IOException("main.npdm inválido");
                }
                // The shared filesystem uses this marker to select direct SAF
                // directory reads instead of looking for an older romfs.bin.
                File root = new File(getFilesDir(), "extracted");
                if (!root.isDirectory() && !root.mkdirs())
                    throw new IOException("Não foi possível preparar a pasta interna do teste");
                File marker = new File(root, ".external-romfs-directory");
                File pending = new File(root, ".external-romfs-directory.partial");
                try (FileOutputStream output = new FileOutputStream(pending)) {
                    output.write(tree.toString().getBytes(StandardCharsets.UTF_8));
                    output.getFD().sync();
                }
                if (!pending.renameTo(marker))
                    throw new IOException("Não foi possível ativar a leitura direta da pasta romfs");
                runOnUiThread(() -> {
                    checking = false;
                    selected = tree;
                    getSharedPreferences("mario_boot", MODE_PRIVATE).edit().putString("game_tree", tree.toString()).apply();
                    play.setEnabled(true);
                    status.setText("Executáveis compatíveis com este APK. Toque em Iniciar teste. " +
                        "Após um fechamento, abra este app novamente e use Ver último log ou Salvar log.");
                });
            } catch (Exception error) {
                runOnUiThread(() -> { checking = false; status.setText("Falha: " + error.getMessage()); });
            }
        }, "mario-folder-check").start();
    }

    private String readLogs() {
        StringBuilder text = new StringBuilder();
        for (String name : new String[]{"mario-exit.log", "neo_touch_crash.txt", "mario-threads.log", "mario-grafico.log", "mario-esperas.log", "lasrecomp_boot.txt", "lasrecomp.log"}) {
            text.append("\n=== ").append(name).append(" ===\n");
            try (RandomAccessFile input = new RandomAccessFile(new File(getFilesDir(), name), "r")) {
                long start = (name.equals("mario-exit.log") || name.equals("neo_touch_crash.txt") || name.equals("mario-threads.log") || name.equals("mario-grafico.log") || name.equals("mario-esperas.log")) ? 0 : Math.max(0, input.length() - 160000);
                input.seek(start);
                byte[] bytes = new byte[(int)(input.length() - start)];
                input.readFully(bytes);
                text.append(new String(bytes, StandardCharsets.UTF_8));
            } catch (Exception error) { text.append("Sem registro de inicialização ainda.\n"); }
        }
        return text.toString();
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (request == PICK_GAME) {
            try {
                getContentResolver().takePersistableUriPermission(uri,
                    data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION);
                validateFolder(uri);
            } catch (Exception error) { status.setText("Falha de permissão: " + error.getMessage()); }
        } else if (request == SAVE_LOG) {
            try (OutputStream output = getContentResolver().openOutputStream(uri, "wt")) {
                if (output == null) throw new java.io.IOException("Não foi possível abrir o destino");
                output.write(readLogs().getBytes(StandardCharsets.UTF_8));
                status.setText("Log salvo.");
            } catch (Exception error) { status.setText("Falha ao salvar: " + error.getMessage()); }
        }
    }
}
