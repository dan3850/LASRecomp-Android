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
    private Button snxProbeButton;
    private Button snxRunButton;
    private static final String SNX_GAME_ID = "010028600EBDA000";

    private void snxStage(String text) {
        android.util.Log.i("MarioSNX", text);
        try (FileOutputStream file = new FileOutputStream(
                new File(getFilesDir(), "mario-snx-launch.log"), true)) {
            file.write((System.currentTimeMillis() + " [launcher] " + text + "\n")
                    .getBytes(StandardCharsets.UTF_8));
            file.getFD().sync();
        } catch (IOException error) {
            android.util.Log.e("MarioSNX", "Cannot save stage", error);
        }
    }

    @Override protected void onResume() {
        super.onResume();
        if (status == null || checking) return;
        File stageFile = new File(getFilesDir(), "mario-snx-launch.log");
        if (!stageFile.isFile()) return;
        // A crashed child process may not recreate this launcher Activity.
        // Refresh Android's retained tombstone information on return.
        savePreviousProcessExits();
        try (RandomAccessFile input = new RandomAccessFile(stageFile, "r")) {
            long first = Math.max(0, input.length() - 5000);
            input.seek(first);
            byte[] bytes = new byte[(int) (input.length() - first)];
            input.readFully(bytes);
            String trace = new String(bytes, StandardCharsets.UTF_8);
            status.setText("Última tentativa ScarletNX:\n" + trace +
                    "\nUse Salvar log para enviar o relatório completo.");
        } catch (IOException ignored) { }
    }
    private static native String nativeProbeScarletNx();

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
        title.setText("Mario SNX Runtime — diagnóstico 3");
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
        play.setText("Iniciar LASRecomp antigo (não é ScarletNX)");
        play.setEnabled(false);
        play.setOnClickListener(v -> {
            if (selected == null || checking) return;
            new File(getFilesDir(), "mario-esperas.log").delete();
            new File(getFilesDir(), "mario-threads.log").delete();
            startActivity(new Intent(this, GameSDLActivity.class).putExtra("game_tree_uri", selected.toString())
                .putExtra("mario_thread_capture", true));
        });
        layout.addView(play);
        snxProbeButton = new Button(this);
        snxProbeButton.setText("Testar biblioteca ScarletNX (sem iniciar o jogo)");
        snxProbeButton.setOnClickListener(v -> runSnxProbe());
        layout.addView(snxProbeButton);
        snxRunButton = new Button(this);
        snxRunButton.setText("INICIAR MARIO — CPU ScarletNX (diagnóstico 2)");
        snxRunButton.setEnabled(false);
        snxRunButton.setOnClickListener(v -> runScarletNxGame());
        layout.addView(snxRunButton);
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

    /** Library is packaged inside this APK; no XCI/SAF permission is needed for this test. */
    private void runSnxProbe() {
        snxProbeButton.setEnabled(false);
        status.setText("Carregando a biblioteca do Mario no processo Android…");
        new Thread(() -> {
            String result;
            try {
                System.loadLibrary("main");
                result = nativeProbeScarletNx();
            } catch (Throwable error) {
                result = "SNX PROBE FAILED: " + error.toString();
            }
            try (FileOutputStream output = new FileOutputStream(
                    new File(getFilesDir(), "mario-snx-probe.txt"), false)) {
                output.write((result + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (IOException error) {
                result += "\nCould not save log: " + error;
            }
            final String message = result;
            runOnUiThread(() -> {
                snxProbeButton.setEnabled(true);
                status.setText(message);
            });
        }, "mario-snx-probe").start();
    }

    /**
     * This runs the actual ScarletNX runtime and its AOT code, in a separate
     * Android process. The runtime requires POSIX-accessible ExeFS; the Zelda
     * SAF bridge used by LASRecomp is not compatible with ScarletNX fs_tree.
     * Copy only needed modules, never the user's private XCI.
     *
     * Do NOT call a compiled GuestFn directly: its CPU/RtAPI/memory layout is
     * ABI-12, unlike the LASRecomp Cpu struct.
     */
    private void runScarletNxGame() {
        final Uri tree = selected;
        if (tree == null || checking) {
            status.setText("Selecione primeiro a pasta Super-extraido.");
            return;
        }
        new File(getFilesDir(), "mario-snx-launch.log").delete();
        snxStage("BUTTON_CLICK: preparing ScarletNX guest execution");
        android.widget.Toast.makeText(this, "Preparando o Mario ScarletNX…", android.widget.Toast.LENGTH_SHORT).show();
        checking = true;
        snxRunButton.setEnabled(false);
        status.setText("ScarletNX: iniciando preparação. Os executáveis podem demorar para copiar; não feche o aplicativo.");
        new Thread(() -> {
            try {
                snxStage("PREPARE: checking packaged runtime and AOT module");
                File nativeDir = new File(getApplicationInfo().nativeLibraryDir);
                File runtime = new File(nativeDir, "libscarletnx.so");
                File code = new File(nativeDir, "libmario_snx.so");
                boolean hasRuntime = runtime.isFile(), hasCode = code.isFile();
                snxStage("NATIVE_LIBRARY_DIR: " + nativeDir.getAbsolutePath() +
                         " exists=" + nativeDir.isDirectory());
                snxStage("INSTALLED LIBS: runtime=" + hasRuntime +
                         " size=" + runtime.length() + "; mario=" + hasCode +
                         " size=" + code.length());
                try (java.util.zip.ZipFile apk =
                             new java.util.zip.ZipFile(getApplicationInfo().sourceDir)) {
                    for (String name : new String[]{"lib/arm64-v8a/libscarletnx.so",
                                                     "lib/arm64-v8a/libmario_snx.so"}) {
                        java.util.zip.ZipEntry entry = apk.getEntry(name);
                        snxStage("APK CONTENTS: " + name + " exists=" + (entry != null) +
                                 " size=" + (entry == null ? 0 : entry.getSize()));
                    }
                } catch (Exception zipError) {
                    snxStage("APK_CONTENTS_FAILED: " + zipError);
                }
                if (!hasRuntime || !hasCode)
                    throw new IOException("Bibliotecas nativas nao instaladas: runtime=" +
                                          hasRuntime + ", mario=" + hasCode +
                                          ". Confira a secao APK CONTENTS no log.");
                snxStage("PREPARE: runtime and Mario AOT module installed");
                File gameRoot = new File(new File(getFilesDir(), "snx-games"), SNX_GAME_ID);
                if (!gameRoot.isDirectory() && !gameRoot.mkdirs())
                    throw new IOException("Não foi possível criar a pasta do jogo.");
                // The Android linker loads the trusted, read-only APK library.
                // The game module is only a symlink; no executable is written
                // to app data, which targetSdk >= 29 prohibits.
                File link = new File(gameRoot, SNX_GAME_ID + "_code.so");
                // File.exists() follows a symlink. A stale link to a native
                // library from the PREVIOUS APK install therefore reports
                // false even though the link itself is still present; calling
                // symlink() then fails with EEXIST. Check the link itself.
                String currentLink = null;
                try {
                    currentLink = android.system.Os.readlink(link.getAbsolutePath());
                } catch (android.system.ErrnoException err) {
                    if (err.errno != android.system.OsConstants.ENOENT &&
                            err.errno != android.system.OsConstants.EINVAL)
                        throw err;
                    if (err.errno == android.system.OsConstants.EINVAL)
                        throw new IOException("Destino AOT existe mas não é link simbólico: " +
                                link.getAbsolutePath(), err);
                }
                if (currentLink != null && !currentLink.equals(code.getAbsolutePath())) {
                    snxStage("PREPARE: replacing stale game AOT link: " + currentLink);
                    // File.delete() removes the symlink itself (without following its target).
                    if (!link.delete())
                        throw new IOException("Não foi possível remover o link AOT antigo: " + link.getAbsolutePath());
                    currentLink = null;
                }
                if (currentLink == null) {
                    android.system.Os.symlink(code.getAbsolutePath(), link.getAbsolutePath());
                    snxStage("PREPARE: created AOT symlink");
                } else {
                    snxStage("PREPARE: reused correct AOT symlink");
                }
                String verifiedLink = android.system.Os.readlink(link.getAbsolutePath());
                if (!code.getAbsolutePath().equals(verifiedLink))
                    throw new IOException("Link do Mario incorreto: " + verifiedLink);
                snxStage("PREPARE: native AOT link ready: " + link.getAbsolutePath());
                File data = new File(gameRoot, SNX_GAME_ID + "_data");
                File exefs = new File(data, "exefs");
                if (!exefs.isDirectory() && !exefs.mkdirs())
                    throw new IOException("Não foi possível criar a pasta ExeFS.");
                for (String module : new String[]{"rtld", "main", "sdk", "main.npdm"}) {
                    final String current = module;
                    snxStage("PREPARE: copying exefs/" + current);
                    runOnUiThread(() -> status.setText("ScarletNX: preparando ExeFS/" + current + "…"));
                    copySnxExecutable(tree, module, new File(exefs, module));
                    snxStage("PREPARE: copied exefs/" + current +
                             " bytes=" + new File(exefs, current).length());
                }
                // Force an app-readable location for the ScarletNX logs and
                // settings, instead of relying on the SDL HOME/XDG defaults.
                File snxState = new File(gameRoot, "state");
                File snxCache = new File(gameRoot, "cache");
                File snxConfig = new File(gameRoot, "config");
                for (File dir : new File[]{snxState, snxCache, snxConfig})
                    if (!dir.isDirectory() && !dir.mkdirs())
                        throw new IOException("Não foi possível criar pasta SNX: " + dir);
                File folders = new File(gameRoot, SNX_GAME_ID + ".folders");
                String foldersText = "state=" + snxState.getAbsolutePath() + "\n"
                        + "cache=" + snxCache.getAbsolutePath() + "\n"
                        + "config=" + snxConfig.getAbsolutePath() + "\n";
                try (FileOutputStream output = new FileOutputStream(folders, false)) {
                    output.write(foldersText.getBytes(StandardCharsets.UTF_8));
                    output.getFD().sync();
                }
                // The runtime builds a dispatch table, loads matching NSOs,
                // initialises Horizon/JIT and attempts kernel_run_main().
                // RomFS remains absent during this FIRST CPU boot attempt:
                // do not silently copy several GB or claim the game will render.
                snxStage("PREPARE_COMPLETE: launching real ScarletNX SDL runtime");
                Intent intent = new Intent(this, MarioSnxGameActivity.class);
                intent.putExtra("snx_game_base",
                        new File(gameRoot, SNX_GAME_ID).getAbsolutePath());
                runOnUiThread(() -> {
                    checking = false;
                    snxRunButton.setEnabled(true);
                    status.setText("Iniciando CPU ScarletNX (ABI 12). Se fechar, use Ver último log.");
                    try {
                        snxStage("ACTIVITY_START_REQUESTED: " + MarioSnxGameActivity.class.getName());
                        startActivity(intent);
                        snxStage("ACTIVITY_START_CALLED: waiting for child process");
                    } catch (Throwable error) {
                        snxStage("ACTIVITY_START_FAILED: " + error.toString());
                        status.setText("ScarletNX: não foi possível abrir a tela do jogo: " + error);
                    }
                });
            } catch (Throwable error) {
                final String message = "SNX PREPARE FAILED: " + error;
                snxStage(message);
                runOnUiThread(() -> {
                    checking = false;
                    snxRunButton.setEnabled(true);
                    status.setText(message + "\n\nToque em Salvar log para enviar o diagnóstico.");
                    android.widget.Toast.makeText(this, "Falha ao preparar ScarletNX; veja o log.", android.widget.Toast.LENGTH_LONG).show();
                });
            }
        }, "mario-snx-prep").start();
    }

    private void copySnxExecutable(Uri tree, String name, File dest) throws IOException {
        // Match each run to the currently selected SAF tree, not a stale cache.
        // Module files are immutable game executables; copy atomically.
        int fd = GameDocumentBridge.openReadFd(this, tree, "exefs/" + name);
        try (InputStream source = new ParcelFileDescriptor.AutoCloseInputStream(
                ParcelFileDescriptor.adoptFd(fd))) {
            File pending = new File(dest.getAbsolutePath() + ".partial");
            try (FileOutputStream output = new FileOutputStream(pending, false)) {
                byte[] buffer = new byte[1024 * 1024];
                int length;
                while ((length = source.read(buffer)) != -1) {
                    output.write(buffer, 0, length);
                }
                output.getFD().sync();
            } catch (IOException error) {
                pending.delete();
                throw error;
            }
            if (!pending.renameTo(dest))
                throw new IOException("Não foi possível guardar ExeFS/" + name);
        }
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
        if (snxRunButton != null) snxRunButton.setEnabled(false);
        status.setText("Verificando os executáveis e o acesso à pasta…");
        new Thread(() -> {
            try {
                if (!GameDocumentBridge.hasPermission(this, tree))
                    throw new java.io.IOException("Selecione a pasta novamente para conceder acesso permanente");
                String lasMismatch = null;
                try {
                    JSONObject builds = profile().getJSONObject("build_ids");
                    checkModule(tree, "main", builds.getString("main"));
                    checkModule(tree, "sdk", builds.getString("sdk"));
                } catch (Exception lasError) {
                    // The ScarletNX AOT module was built from Super.xci, which
                    // may differ from LASRecomp's separately extracted NSOs.
                    // Only disable the LASRecomp boot; SNX verifies its own
                    // NSO build IDs before running CPU instructions.
                    lasMismatch = lasError.getMessage();
                }
                final String lasReason = lasMismatch;
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
                    play.setEnabled(lasReason == null);
                    snxRunButton.setEnabled(true);
                    status.setText(lasReason == null ?
                        "Executáveis compatíveis. Escolha Iniciar teste (LAS) ou Executar Mario pelo runtime ScarletNX." :
                        "Atenção: LASRecomp não corresponde a esta extração (" + lasReason + "). " +
                        "ScarletNX disponível: o runtime verificará suas próprias versões do jogo.");
                });
            } catch (Exception error) {
                runOnUiThread(() -> { checking = false; status.setText("Falha: " + error.getMessage()); });
            }
        }, "mario-folder-check").start();
    }

    private String readLogs() {
        StringBuilder text = new StringBuilder();
        boolean scarletAttempt = new File(getFilesDir(), "mario-snx-launch.log").isFile();
        String[] logs = scarletAttempt ?
                new String[]{"mario-snx-launch.log", "mario-snx-probe.txt", "mario-exit.log"} :
                new String[]{"mario-exit.log", "neo_touch_crash.txt", "mario-threads.log",
                             "mario-grafico.log", "mario-esperas.log", "lasrecomp_boot.txt", "lasrecomp.log"};
        for (String name : logs) {
            text.append("\n=== ").append(name).append(" ===\n");
            try (RandomAccessFile input = new RandomAccessFile(new File(getFilesDir(), name), "r")) {
                long start = (name.equals("mario-exit.log") || name.equals("neo_touch_crash.txt") || name.equals("mario-threads.log") || name.equals("mario-grafico.log") || name.equals("mario-esperas.log")) ? 0 : Math.max(0, input.length() - 160000);
                input.seek(start);
                byte[] bytes = new byte[(int)(input.length() - start)];
                input.readFully(bytes);
                text.append(new String(bytes, StandardCharsets.UTF_8));
            } catch (Exception error) { text.append("Sem registro de inicialização ainda.\n"); }
        }
        File snxState = new File(new File(new File(getFilesDir(),
                "snx-games"), SNX_GAME_ID), "state");
        File[] recorded = snxState.listFiles();
        if (recorded != null) {
            java.util.Arrays.sort(recorded, (a, b) ->
                    Long.compare(b.lastModified(), a.lastModified()));
            int added = 0;
            for (File file : recorded) {
                if (!file.isFile() || !file.getName().endsWith(".log")) continue;
                text.append("\n=== SNX RUNTIME: ").append(file.getName()).append(" ===\n");
                try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
                    long start = Math.max(0, input.length() - 240000);
                    input.seek(start);
                    byte[] bytes = new byte[(int)(input.length() - start)];
                    input.readFully(bytes);
                    text.append(new String(bytes, StandardCharsets.UTF_8));
                } catch (IOException error) {
                    text.append("Não foi possível ler log SNX: ").append(error);
                }
                if (++added >= 3) break;
            }
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
