package com.retroaura.lasrecomp;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
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

    private static final int PICK_GAME_FOLDER = 101;
    private TextView status;
    private Button importButton;
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
        layout.setGravity(Gravity.CENTER);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("LASRecomp Android");
        title.setTextSize(24);
        title.setGravity(Gravity.CENTER);
        layout.addView(title);

        status = new TextView(this);
        status.setTextSize(16);
        status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, -2);
        statusParams.topMargin = pad;
        statusParams.bottomMargin = pad;
        layout.addView(status, statusParams);

        importButton = new Button(this);
        importButton.setText("IMPORTAR ARQUIVOS DO JOGO");
        importButton.setOnClickListener(v -> pickGameFolder());
        layout.addView(importButton);
        playButton = new Button(this);
        playButton.setText("JOGAR");
        playButton.setVisibility(View.GONE);
        playButton.setOnClickListener(v -> {
            if (!importing && hasGameFiles(extractedDir()) && hasGameCode()) {
                Intent game = new Intent();
                game.setClassName(this, "com.retroaura.lasrecomp.GameSDLActivity");
                startActivity(game);
            }
        });
        layout.addView(playButton);
        setContentView(layout);
        showGameFilesState();
    }

    private File extractedDir() {
        return new File(getFilesDir(), "extracted");
    }

    private boolean hasGameFiles(File root) {
        return new File(root, "exefs/main").isFile()
            && new File(root, "exefs/sdk").isFile()
            && new File(root, "exefs/main.npdm").isFile()
            && new File(root, "romfs/region_common").isDirectory()
            && new File(root, "romfs.bin").isFile();
    }

    private boolean hasGameCode() {
        // android:extractNativeLibs=true; code must come from the signed APK,
        // never from app-private writable game data or a Termux filesystem.
        String dir = getApplicationInfo().nativeLibraryDir;
        return dir != null && new File(dir, "liblasgame.so").isFile()
            && new File(dir, "liblasrecomp_runtime.so").isFile();
    }

    private void showGameFilesState() {
        boolean files = hasGameFiles(extractedDir());
        boolean code = hasGameCode();
        playButton.setVisibility(files && code && !importing ? View.VISIBLE : View.GONE);
        if (files && code) {
            status.setText("Arquivos e código recompilado disponíveis.\nPronto para tentar iniciar o jogo.");
        } else if (files) {
            status.setText("Arquivos do jogo importados.\nAinda falta o código recompilado dentro deste APK.");
        } else {
            status.setText("Selecione a pasta com exefs e romfs da sua cópia do jogo v1.0.0.\n"
                + "Os arquivos serão guardados apenas neste aplicativo."
                + (code ? "\nO código do jogo já está instalado neste APK." : ""));
        }
    }

    private void pickGameFolder() {
        if (importing) return;
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION |
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(picker, PICK_GAME_FOLDER);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
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
        playButton.setVisibility(View.GONE);
        status.setText("Copiando e preparando os arquivos do jogo...");
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
            copyTree(tree, exefs, new File(stage, "exefs"), 0);
            copyTree(tree, romfs, new File(stage, "romfs"), 0);
            // Prepare the actual binary RomFS image the guest reads. The bridge
            // also validates the exact v1.0.0 build ID before accepting the game.
            runOnUiThread(() -> status.setText("Criando romfs.bin a partir da ROMFS..."));
            String prepareError = nativePrepareGame(stage.getAbsolutePath());
            if (prepareError != null) throw new IllegalStateException(prepareError);
            if (!hasGameFiles(stage))
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
        } catch (Exception e) {
            error = e.getMessage() == null ? e.toString() : e.getMessage();
        } finally {
            try { if (stage.exists()) removeTree(stage); } catch (Exception ignored) {}
        }
        final String result = error;
        runOnUiThread(() -> {
            importing = false;
            importButton.setEnabled(true);
            if (result != null) {
                new AlertDialog.Builder(this).setTitle("Importação não concluída")
                    .setMessage(result).setPositiveButton("OK", null).show();
            }
            showGameFilesState();
        });
    }
}
