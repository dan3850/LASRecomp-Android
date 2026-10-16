package com.retroaura.lasrecomp;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.FileInputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * The real Android application entry point. Users import their own extracted
 * Link's Awakening 1.0.0 game files directly into app-private storage.
 * No shell, Termux, or external executable is invoked.
 *
 * Only offer a game launch when both the real imported files and a privately
 * installed ARM64 game-code library are present; no diagnostic boot screen.
 */
public final class GameImportActivity extends Activity {
    // Real LASRecomp RomFS builder, packaged inside this APK (no Termux).
    static { System.loadLibrary("lasrecomp_prepare"); }
    private static native String nativePrepareGame(String stageDirectory);
    // Feasibility test: loads ONLY a harmless probe library, not game code.
    private static native String nativeProbeLocalCode(String libraryPath, String cacheDirectory);
    private static native String nativeCheckGameCode(String libraryPath);

    private static final String GAME_TREE_PREF = "selected_game_tree";
    private static final int PICK_GAME_FOLDER = 101;
    private static final int PICK_GAME_CODE = 102;
    private static final int PICK_SYSTEM_FONT = 103;
    // Test route only: the final release will compile this file inside the app.
    private static final long MAX_LIBRARY_BYTES = 1024L * 1024L * 1024L;
    private TextView status;
    private Button importButton;
    private Button libraryButton;
    private Button fontButton;
    private Button verifyButton;
    private Button playButton;
    private boolean importing;

    private static final class Entry {
        final Uri uri;
        final String name;
        final String mime;
        Entry(Uri uri, String name, String mime) {
            this.uri = uri; this.name = name; this.mime = mime;
        }
        boolean directory() {
            return DocumentsContract.Document.MIME_TYPE_DIR.equals(mime);
        }
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER_HORIZONTAL);
        // Keep the primary action visible even on short landscape screens.
        int pad = (int) (12 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad, pad, pad);

        status = new TextView(this);
        status.setTextSize(16);
        status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, -2);
        statusParams.topMargin = pad / 2;
        statusParams.bottomMargin = pad;
        layout.addView(status, statusParams);

        // Never silently hide Play below a diagnostic area.
        // Disabled until the real game's code and files are available.
        playButton = new Button(this);
        playButton.setText("JOGAR");
        playButton.setOnClickListener(v -> {
            if (!importing && hasGameFiles(extractedDir()) && hasGameCode()) {
                Intent game = new Intent();
                game.setClassName(this, "com.retroaura.lasrecomp.GameSDLActivity");
                Uri tree = rememberedGameFolder();
                if (tree != null) game.putExtra("game_tree_uri", tree.toString());
                startActivity(game);
            }
        });
        layout.addView(playButton);

        importButton = new Button(this);
        importButton.setText("IMPORTAR ARQUIVOS DO JOGO");
        importButton.setOnClickListener(v -> pickGameFolder());
        layout.addView(importButton);

        libraryButton = new Button(this);
        libraryButton.setText("TESTE: IMPORTAR MINHA LIBLASGAME.SO");
        libraryButton.setOnClickListener(v -> selectGameCodeFile());
        layout.addView(libraryButton);

        // System fonts are console-owned, not stored in Zelda's NSP or our APK.
        // Users may import their own legitimate Switch Standard/NintendoExt font.
        fontButton = new Button(this);
        fontButton.setText("IMPORTAR FONTE DO MEU SWITCH (OPCIONAL)");
        fontButton.setOnClickListener(v -> selectSystemFont());
        layout.addView(fontButton);

        verifyButton = new Button(this);
        verifyButton.setText("TESTE: VERIFICAR BIBLIOTECA DO ZELDA");
        verifyButton.setOnClickListener(v -> {
            if (importing) return;
            verifyButton.setEnabled(false);
            new Thread(() -> {
                String result;
                try {
                    result = nativeCheckGameCode(privateGameCodeFile().getAbsolutePath());
                } catch (Throwable error) {
                    result = "FALHOU: " + error;
                }
                final String message = result;
                runOnUiThread(() -> {
                    verifyButton.setEnabled(true);
                    new AlertDialog.Builder(this)
                        .setTitle("Compatibilidade com o motor")
                        .setMessage(message)
                        .setPositiveButton("OK", null).show();
                });
            }, "LASRecompVerifyRealGame").start();
        });
        layout.addView(verifyButton);

        // Separate diagnostic on the experimental branch. No game files are
        // compiled or loaded by this test; it only checks Android linker policy.
        Button probeButton = new Button(this);
        probeButton.setText("DIAGNÓSTICO: TESTAR BIBLIOTECA LOCAL");
        probeButton.setOnClickListener(v -> {
            probeButton.setEnabled(false);
            new Thread(() -> {
                String result;
                try {
                    File source = new File(getApplicationInfo().nativeLibraryDir,
                                           "liblasrecomp_probe.so");
                    result = nativeProbeLocalCode(source.getAbsolutePath(),
                                                  getCodeCacheDir().getAbsolutePath());
                } catch (Throwable error) {
                    result = "FALHOU: " + error;
                }
                final String diagnostic = result;
                runOnUiThread(() -> {
                    probeButton.setEnabled(true);
                    new AlertDialog.Builder(this)
                        .setTitle("Teste do carregamento nativo")
                        .setMessage(diagnostic)
                        .setPositiveButton("OK", null)
                        .show();
                });
            }, "LASRecompLocalLoaderProbe").start();
        });
        layout.addView(probeButton);
        Button bootLogButton = new Button(this);
        bootLogButton.setText("VER REGISTRO DO BOOT");
        bootLogButton.setOnClickListener(v -> showBootLog());
        layout.addView(bootLogButton);
        ScrollView scroller = new ScrollView(this);
        scroller.setFillViewport(false);
        scroller.setVerticalScrollBarEnabled(true);
        scroller.setScrollbarFadingEnabled(false);
        scroller.addView(layout, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.MATCH_PARENT, ScrollView.LayoutParams.WRAP_CONTENT));
        setContentView(scroller);
        showGameFilesState();
    }

    // Read only a bounded tail of the app's own diagnostic files. The runtime
    // writes these before/after the guest memory reservation and during boot.
    private static String readLogTail(File file, int maxBytes) {
        if (!file.isFile()) return "(arquivo ainda nao criado)";
        try (RandomAccessFile stream = new RandomAccessFile(file, "r")) {
            long size = stream.length();
            int bytes = (int) Math.min(size, maxBytes);
            byte[] content = new byte[bytes];
            stream.seek(size - bytes);
            stream.readFully(content);
            return (size > bytes ? "(ultimos " + bytes + " bytes)\n" : "")
                 + new String(content, StandardCharsets.UTF_8);
        } catch (Exception error) {
            return "(erro ao ler: " + error.getMessage() + ")";
        }
    }

    private void showBootLog() {
        String boot = readLogTail(new File(getFilesDir(), "lasrecomp_boot.txt"), 10000);
        String runtime = readLogTail(new File(getFilesDir(), "lasrecomp.log"), 16000);
        String output = "=== INICIO / SDL ===\n" + boot
                      + "\n\n=== MOTOR NATIVO ===\n" + runtime;
        new AlertDialog.Builder(this)
            .setTitle("Diagnostico do boot")
            .setMessage(output)
            .setNegativeButton("FECHAR", null)
            .setPositiveButton("COPIAR REGISTRO", (dialog, which) -> {
                ClipboardManager clipboard =
                    (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                if (clipboard != null)
                    clipboard.setPrimaryClip(ClipData.newPlainText("LASRecomp boot", output));
            }).show();
    }

    private File extractedDir() {
        return new File(getFilesDir(), "extracted");
    }

    private File privateGameCodeFile() {
        return new File(getCodeCacheDir(), "liblasgame.so");
    }

    private void selectSystemFont() {
        if (importing) return;
        new AlertDialog.Builder(this)
            .setTitle("Fonte de sistema do seu Switch")
            .setMessage("A fonte padrão do APK é apenas uma substituta. Se você extraiu legalmente de seu próprio Switch os arquivos nintendo_udsg-r_std_003.bfttf ou nintendo_ext_003.bfttf (ou versões .ttf), pode importar um por vez. Esses arquivos não fazem parte do Zelda NSP, não são enviados e não serão incluídos no APK. Reinicie o jogo após importar.")
            .setNegativeButton("Cancelar", null)
            .setPositiveButton("Selecionar fonte", (dialog, which) -> {
                Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                picker.addCategory(Intent.CATEGORY_OPENABLE);
                picker.setType("*/*");
                picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                startActivityForResult(picker, PICK_SYSTEM_FONT);
            }).show();
    }

    private static int le32(byte[] b, int o) {
        return (b[o] & 255) | ((b[o + 1] & 255) << 8)
            | ((b[o + 2] & 255) << 16) | ((b[o + 3] & 255) << 24);
    }

    private void importSystemFont(Uri source) {
        String error = null;
        String installed = null;
        File temporary = null;
        try {
            String sourceName = null;
            try (Cursor c = getContentResolver().query(source,
                    new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
                if (c != null && c.moveToFirst()) sourceName = c.getString(0);
            }
            if (sourceName == null) throw new IllegalStateException("Arquivo sem nome");
            String n = sourceName.toLowerCase(java.util.Locale.ROOT);
            boolean standard = n.startsWith("nintendo_udsg-r_std_003.")
                || n.startsWith("nintendo_udsgr_std_003.");
            boolean ext = n.startsWith("nintendo_ext_003.");
            boolean bfttf = n.endsWith(".bfttf");
            boolean ttf = n.endsWith(".ttf");
            if ((!standard && !ext) || (!bfttf && !ttf))
                throw new IllegalStateException("Selecione nintendo_udsg-r_std_003 ou nintendo_ext_003, em .bfttf ou .ttf");
            String targetName = (standard ? "nintendo_udsg-r_std_003" : "nintendo_ext_003")
                + (bfttf ? ".bfttf" : ".ttf");
            File dir = new File(getFilesDir(), "fonts");
            if (!dir.isDirectory() && !dir.mkdirs())
                throw new IllegalStateException("Não foi possível criar a pasta das fontes");
            temporary = File.createTempFile(".lasrecomp-font-", ".tmp", dir);
            long copied = 0;
            try (InputStream in = getContentResolver().openInputStream(source);
                 FileOutputStream out = new FileOutputStream(temporary)) {
                if (in == null) throw new IllegalStateException("Não foi possível abrir o arquivo");
                byte[] buffer = new byte[65536];
                int count;
                while ((count = in.read(buffer)) != -1) {
                    copied += count;
                    if (copied > 64L * 1024L * 1024L)
                        throw new IllegalStateException("Fonte maior que 64 MB");
                    out.write(buffer, 0, count);
                }
                out.getFD().sync();
            }
            if (copied < 1024) throw new IllegalStateException("Fonte pequena ou vazia");
            byte[] h = new byte[12];
            try (FileInputStream in = new FileInputStream(temporary)) {
                if (in.read(h) < h.length) throw new IllegalStateException("Cabeçalho incompleto");
            }
            int sfnt = le32(h, 0);
            if (bfttf) {
                int ver = le32(h, 8);
                int key = 0x49621806;
                if (!((ver ^ key) == 0x00000100 || (ver ^ key) == 0x4F54544F
                    || (ver ^ Integer.reverseBytes(key)) == 0x00000100
                    || (ver ^ Integer.reverseBytes(key)) == 0x4F54544F))
                    throw new IllegalStateException("Arquivo .bfttf inválido");
            } else if (!(sfnt == 0x00000100 || sfnt == 0x4F54544F || sfnt == 0x66637474)) {
                // sfnt 1.0, OpenType (OTTO) or TTC (ttcf) in little endian.
                throw new IllegalStateException("Arquivo .ttf não reconhecido");
            }
            File destination = new File(dir, targetName);
            java.nio.file.Files.move(temporary.toPath(), destination.toPath(),
                java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            temporary = null;
            installed = targetName;
        } catch (Exception e) {
            error = e.getMessage() == null ? e.toString() : e.getMessage();
        } finally {
            if (temporary != null) temporary.delete();
        }
        final String failure = error, success = installed;
        runOnUiThread(() -> {
            importing = false;
            importButton.setEnabled(true);
            libraryButton.setEnabled(true);
            fontButton.setEnabled(true);
            showGameFilesState();
            new AlertDialog.Builder(this)
                .setTitle(failure == null ? "Fonte importada" : "Falha ao importar fonte")
                .setMessage(failure == null
                    ? success + " instalado na pasta privada. Feche o Zelda e abra novamente para testar os textos e símbolos."
                    : failure)
                .setPositiveButton("OK", null).show();
        });
    }

    private void selectGameCodeFile() {
        if (importing) return;
        new AlertDialog.Builder(this)
            .setTitle("Importar biblioteca do próprio jogo")
            .setMessage("A biblioteca .so contém código executável derivado do Zelda. " +
                "Selecione somente a que você mesmo compilou. Ela será copiada " +
                "para o armazenamento privado do aplicativo e não será enviada à internet.")
            .setNegativeButton("Cancelar", null)
            .setPositiveButton("Selecionar arquivo", (dialog, which) -> {
                Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                picker.addCategory(Intent.CATEGORY_OPENABLE);
                picker.setType("*/*");
                picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                startActivityForResult(picker, PICK_GAME_CODE);
            }).show();
    }

    private void importGameCode(Uri source) {
        String error = null;
        File temporary = null;
        try {
            // Limit the filename to our expected output: no arbitrary native plugin.
            String sourceName = null;
            try (Cursor c = getContentResolver().query(source,
                    new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
                if (c != null && c.moveToFirst()) sourceName = c.getString(0);
            }
            if (!"liblasgame.so".equals(sourceName))
                throw new IllegalStateException("Selecione somente o arquivo liblasgame.so");

            File cache = getCodeCacheDir();
            if (!cache.isDirectory()) throw new IllegalStateException("Cache privado inacessível");
            temporary = File.createTempFile(".liblasgame-", ".partial", cache);
            long copied = 0L;
            try (InputStream in = getContentResolver().openInputStream(source);
                 FileOutputStream out = new FileOutputStream(temporary)) {
                if (in == null) throw new IllegalStateException("Não foi possível ler o arquivo");
                byte[] data = new byte[262144];
                int n;
                long previousProgress = 0;
                while ((n = in.read(data)) != -1) {
                    copied += n;
                    if (copied > MAX_LIBRARY_BYTES)
                        throw new IllegalStateException("Biblioteca maior que 1 GB");
                    out.write(data, 0, n);
                    if (copied - previousProgress >= 8 * 1024 * 1024) {
                        previousProgress = copied;
                        final long sizeMb = copied / (1024 * 1024);
                        runOnUiThread(() -> status.setText(
                            "Copiando biblioteca privada: " + sizeMb + " MB"));
                    }
                }
                out.getFD().sync();
            }
            if (copied < 1024) throw new IllegalStateException("Biblioteca incompleta");

            // Check ELF64 little-endian ET_DYN/AArch64; prevent wrong-architecture files.
            try (RandomAccessFile elf = new RandomAccessFile(temporary, "r")) {
                byte[] hdr = new byte[20];
                elf.readFully(hdr);
                if ((hdr[0] & 255) != 0x7f || hdr[1] != 'E' || hdr[2] != 'L' ||
                    hdr[3] != 'F' || hdr[4] != 2 || hdr[5] != 1 ||
                    hdr[16] != 3 || hdr[17] != 0 || (hdr[18] & 255) != 183 || hdr[19] != 0)
                    throw new IllegalStateException("Não é uma biblioteca ELF ARM64 compartilhada");
            }
            // Android 14+ prohibits dlopen of an app-writable executable.
            if (!temporary.setReadable(true, true) || !temporary.setWritable(false, false) ||
                temporary.canWrite()) {
                throw new IllegalStateException("Não consegui tornar a biblioteca somente leitura");
            }
            File destination = privateGameCodeFile();
            if (!temporary.renameTo(destination))
                throw new IllegalStateException("Falha ao instalar biblioteca privada");
            temporary = null;
        } catch (Exception e) {
            error = e.getMessage() == null ? e.toString() : e.getMessage();
        } finally {
            if (temporary != null) temporary.delete();
        }
        final String failure = error;
        runOnUiThread(() -> {
            importing = false;
            importButton.setEnabled(true);
            libraryButton.setEnabled(true);
            if (failure == null) {
                new AlertDialog.Builder(this)
                    .setTitle("Biblioteca importada")
                    .setMessage("A liblasgame.so está no cache privado. O próximo teste " +
                                "é abrir o jogo para verificar compatibilidade com o motor. " +
                                "Ainda não está confirmado que o Zelda inicia.")
                    .setPositiveButton("OK", null).show();
            } else {
                new AlertDialog.Builder(this)
                    .setTitle("Biblioteca não importada")
                    .setMessage(failure).setPositiveButton("OK", null).show();
            }
            showGameFilesState();
        });
    }


    private boolean hasGameFiles(File root) {
        return new File(root, "exefs/main").isFile()
            && new File(root, "exefs/sdk").isFile()
            && new File(root, "exefs/main.npdm").isFile()
            && (new File(root, "romfs.bin").isFile()
                || (new File(root, ".external-romfs").isFile()
                    && rememberedGameFolder() != null));
    }

    private boolean hasGameCode() {
        File privateCode = privateGameCodeFile();
        String dir = getApplicationInfo().nativeLibraryDir;
        return dir != null && new File(dir, "liblasrecomp_runtime.so").isFile()
            && ((privateCode.isFile() && privateCode.length() > 1024 && !privateCode.canWrite())
                || new File(dir, "liblasgame.so").isFile());
    }

    private void showGameFilesState() {
        boolean files = hasGameFiles(extractedDir());
        boolean code = hasGameCode();
        playButton.setVisibility(View.VISIBLE);
        playButton.setEnabled(files && code && !importing);
        playButton.setText(files && code ? "JOGAR" : "JOGAR — AGUARDANDO ARQUIVOS E BIBLIOTECA");
        verifyButton.setVisibility(privateGameCodeFile().isFile() ? View.VISIBLE : View.GONE);
        verifyButton.setEnabled(!importing);
        fontButton.setEnabled(!importing);
        if (files && code) {
            status.setText("Arquivos e código recompilado disponíveis.\nPronto para tentar iniciar o jogo.");
        } else if (files) {
            status.setText("Arquivos do jogo importados.\nImporte sua liblasgame.so de teste para tentar iniciar o jogo.");
        } else {
            status.setText("Selecione a pasta com exefs e romfs da sua cópia do jogo v1.0.0.\n"
                + "Os arquivos serão guardados apenas neste aplicativo."
                + (code ? "\nO código do jogo já está instalado neste APK." : ""));
        }
    }

    private Uri rememberedGameFolder() {
        String saved = getPreferences(MODE_PRIVATE).getString(GAME_TREE_PREF, null);
        if (saved == null) return null;
        Uri uri = Uri.parse(saved);
        for (android.content.UriPermission grant : getContentResolver().getPersistedUriPermissions()) {
            if (grant.isReadPermission() && uri.equals(grant.getUri())) return uri;
        }
        return null;
    }

    private void pickGameFolder() {
        if (importing) return;
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION |
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        Uri previous = rememberedGameFolder();
        if (previous != null && android.os.Build.VERSION.SDK_INT >= 26)
            picker.putExtra(DocumentsContract.EXTRA_INITIAL_URI, previous);
        startActivityForResult(picker, PICK_GAME_FOLDER);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PICK_SYSTEM_FONT) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                importing = true;
                importButton.setEnabled(false);
                libraryButton.setEnabled(false);
                fontButton.setEnabled(false);
                playButton.setEnabled(false);
                status.setText("Importando fonte do próprio console...");
                Uri source = data.getData();
                new Thread(() -> importSystemFont(source), "LASRecompFontImport").start();
            }
            return;
        }
        if (requestCode == PICK_GAME_CODE) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                importing = true;
                importButton.setEnabled(false);
                libraryButton.setEnabled(false);
                verifyButton.setEnabled(false);
                playButton.setEnabled(false);
                status.setText("Preparando biblioteca privada...");
                Uri gameCode = data.getData();
                new Thread(() -> importGameCode(gameCode), "LASRecompPrivateCodeImport").start();
            }
            return;
        }
        if (requestCode != PICK_GAME_FOLDER || resultCode != RESULT_OK ||
            data == null || data.getData() == null) return;
        Uri tree = data.getData();
        try {
            getContentResolver().takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (SecurityException ignored) {
            // The transient URI grant remains usable for this import.
        }
        importing = true;
        importButton.setEnabled(false);
        libraryButton.setEnabled(false);
        verifyButton.setEnabled(false);
        playButton.setEnabled(false);
        status.setText("Verificando arquivos externos e preparando o jogo...");
        new Thread(() -> importTree(tree), "LASRecompImport").start();
    }

    private List<Entry> children(Uri tree, String parentId) {
        Uri childUri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
        List<Entry> found = new ArrayList<>();
        String[] columns = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE
        };
        try (Cursor c = getContentResolver().query(childUri, columns, null, null, null)) {
            if (c == null) throw new IllegalStateException("Não foi possível abrir a pasta");
            while (c.moveToNext()) {
                String documentId = c.getString(0);
                String name = c.getString(1);
                String mime = c.getString(2);
                if (name == null || name.isEmpty()) continue;
                found.add(new Entry(
                    DocumentsContract.buildDocumentUriUsingTree(tree, documentId), name, mime));
            }
        }
        return found;
    }

    private String documentId(Entry entry) {
        return DocumentsContract.getDocumentId(entry.uri);
    }

    private boolean hasNamedFile(List<Entry> entries, String name) {
        for (Entry entry : entries)
            if (!entry.directory() && name.equals(entry.name)) return true;
        return false;
    }

    private Entry namedFolder(List<Entry> entries, String name) {
        for (Entry e : entries) {
            if (e.directory() && name.equals(e.name)) return e;
        }
        return null;
    }

    private void copyTree(Uri tree, Entry folder, File dest, int depth) throws Exception {
        if (depth > 48) throw new IllegalStateException("Pasta muito profunda");
        if (!dest.isDirectory() && !dest.mkdirs()) throw new IllegalStateException("Falha ao criar pasta");
        for (Entry e : children(tree, documentId(folder))) {
            if (".".equals(e.name) || "..".equals(e.name) ||
                e.name.contains("/") || e.name.contains("\\") || e.name.indexOf('\u0000') >= 0) {
                throw new IllegalStateException("Nome de arquivo inválido");
            }
            File output = new File(dest, e.name);
            if (e.directory()) {
                copyTree(tree, e, output, depth + 1);
            } else {
                try (InputStream in = getContentResolver().openInputStream(e.uri)) {
                    if (in == null) throw new IllegalStateException("Falha ao abrir " + e.name);
                    try (FileOutputStream out = new FileOutputStream(output)) {
                        byte[] buf = new byte[131072];
                        int n;
                        while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
                    }
                }
            }
        }
    }

    private static void removeTree(File f) {
        if (f.isDirectory()) {
            File[] children = f.listFiles();
            if (children != null) for (File child : children) removeTree(child);
        }
        if (f.exists() && !f.delete()) throw new IllegalStateException("Falha ao limpar pasta");
    }

    private boolean hasPersistedReadGrant(Uri tree) {
        for (android.content.UriPermission grant : getContentResolver().getPersistedUriPermissions()) {
            if (grant.isReadPermission() && tree.equals(grant.getUri())) return true;
        }
        return false;
    }

    private void importTree(Uri tree) {
        String error = null;
        File stage = new File(getFilesDir(), "extracted.importing");
        File destination = extractedDir();
        try {
            if (stage.exists()) removeTree(stage);
            if (!stage.mkdir()) throw new IllegalStateException("Sem acesso ao armazenamento interno");

            String rootId = DocumentsContract.getTreeDocumentId(tree);
            List<Entry> root = children(tree, rootId);
            Entry exefs = namedFolder(root, "exefs");
            Entry romfs = namedFolder(root, "romfs");
            if (exefs == null || romfs == null)
                throw new IllegalStateException("Escolha a pasta que contém exefs e romfs");
            // Validate the SAF tree before copying large game data.
            List<Entry> exefsFiles = children(tree, documentId(exefs));
            if (!hasNamedFile(exefsFiles, "main") ||
                !hasNamedFile(exefsFiles, "sdk") ||
                !hasNamedFile(exefsFiles, "main.npdm"))
                throw new IllegalStateException("Pasta exefs incompleta: main, sdk ou main.npdm ausente");
            if (!hasNamedFile(root, "romfs.bin") &&
                namedFolder(children(tree, documentId(romfs)), "region_common") == null)
                throw new IllegalStateException("Pasta romfs incompleta: region_common ausente");
            // Fast path: the user's folder already contains a prepared RomFS
            // image. Keep that large image outside the APK's private storage.
            // Only the relatively small executable files are staged locally.
            boolean externalImage = hasNamedFile(root, "romfs.bin");
            if (externalImage && !hasPersistedReadGrant(tree))
                throw new IllegalStateException("Permissão permanente necessária para ler romfs.bin");
            copyTree(tree, exefs, new File(stage, "exefs"), 0);
            if (externalImage) {
                try (FileOutputStream marker = new FileOutputStream(new File(stage, ".external-romfs"))) {
                    marker.write(1);
                }
            } else {
                copyTree(tree, romfs, new File(stage, "romfs"), 0);
            }
            // Prepare the actual binary RomFS image the guest reads. The bridge
            // also validates the exact v1.0.0 build ID before accepting the game.
            runOnUiThread(() -> status.setText("Criando romfs.bin a partir da ROMFS..."));
            if (externalImage) {
                // Native preparation builds a second huge image; avoid it when
                // a ready-to-read external image was supplied. Validate NSO ID.
                try (RandomAccessFile main = new RandomAccessFile(new File(stage, "exefs/main"), "r")) {
                    byte[] id = new byte[8];
                    main.seek(0x40);
                    main.readFully(id);
                    byte[] expected = {(byte)0xae,0x16,(byte)0xf7,0x1e,0x00,0x2a,(byte)0xf8,(byte)0xcb};
                    if (!java.util.Arrays.equals(id, expected))
                        throw new IllegalStateException("Versão do jogo incompatível (necessária v1.0.0)");
                }
                try (android.os.ParcelFileDescriptor fd = getContentResolver().openFileDescriptor(
                        GameDocumentBridge.child(this, tree, "romfs.bin"), "r")) {
                    if (fd == null || fd.getStatSize() < 512)
                        throw new IllegalStateException("romfs.bin externo ausente ou vazio");
                    if (android.system.Os.lseek(fd.getFileDescriptor(), 0,
                            android.system.OsConstants.SEEK_CUR) < 0)
                        throw new IllegalStateException("romfs.bin não permite acesso aleatório");
                }
            } else {
                String prepareError = nativePrepareGame(stage.getAbsolutePath());
                if (prepareError != null) throw new IllegalStateException(prepareError);
            }
            boolean stageValid = new File(stage, "exefs/main").isFile()
                && new File(stage, "exefs/sdk").isFile()
                && new File(stage, "exefs/main.npdm").isFile()
                && (externalImage
                    ? new File(stage, ".external-romfs").isFile() && hasPersistedReadGrant(tree)
                    : new File(stage, "romfs.bin").isFile());
            if (!stageValid)
                throw new IllegalStateException("Não foi possível preparar todos os arquivos do jogo");

            // Do not erase a previous valid game until the new import is complete.
            File previous = new File(getFilesDir(), "extracted.previous");
            if (previous.exists()) removeTree(previous);
            if (destination.exists() && !destination.renameTo(previous))
                throw new IllegalStateException("Não foi possível preservar a importação anterior");
            if (!stage.renameTo(destination)) {
                if (previous.exists()) previous.renameTo(destination);
                throw new IllegalStateException("Não foi possível finalizar a importação");
            }
            if (previous.exists()) removeTree(previous);
            // Keep the SAF grant so external RomFS remains readable on next launch.
            if (hasPersistedReadGrant(tree))
                getPreferences(MODE_PRIVATE).edit().putString(GAME_TREE_PREF, tree.toString()).apply();
        } catch (Exception e) {
            error = e.getMessage() == null ? e.toString() : e.getMessage();
        } finally {
            try { if (stage.exists()) removeTree(stage); } catch (Exception ignored) {}
        }
        final String result = error;
        runOnUiThread(() -> {
            importing = false;
            importButton.setEnabled(true);
            libraryButton.setEnabled(true);
            if (result != null) {
                new AlertDialog.Builder(this).setTitle("Importação não concluída")
                    .setMessage(result).setPositiveButton("OK", null).show();
            }
            showGameFilesState();
        });
    }
}
