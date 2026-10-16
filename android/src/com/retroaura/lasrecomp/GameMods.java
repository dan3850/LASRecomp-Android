package com.retroaura.lasrecomp;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.text.InputType;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.InputStream;

/** Android mod controls; imported patches only activate prepared code variants. */
public final class GameMods {
    public static final int PICK_FILE = 106;
    private GameMods() {}

    public static void show(Activity activity, boolean prepared) {
        File directory = new File(activity.getFilesDir(), "mods");
        boolean imported = Stable60Patch.imported(directory);
        LinearLayout layout = new LinearLayout(activity);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(20 * activity.getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad, pad, pad);
        TextView status = new TextView(activity);
        status.setText("Stable 60fps v2 — Link's Awakening 1.0.0\n" +
            (imported ? "Mod importado.\n" : "Importe o arquivo .pchtxt ou cole o código do mod.\n") +
            (prepared ? "Biblioteca compatível com ativar/desativar." :
             "A biblioteca atual ainda não permite ativar/desativar pelo menu. " +
             "Prepare e importe a biblioteca compatível uma vez. Reinicie o aplicativo após trocar a biblioteca.") +
            "\nOutros mods ainda não são compatíveis com este menu.");
        layout.addView(status);
        File lastRun = new File(directory, "stable60-v2.status.txt");
        if (lastRun.isFile() && lastRun.length() <= 4096) {
            try (InputStream input = new java.io.FileInputStream(lastRun)) {
                TextView execution = new TextView(activity);
                execution.setText("\nÚLTIMA SESSÃO REGISTRADA\n" + Stable60Patch.read(input));
                layout.addView(execution);
            } catch (java.io.IOException ignored) { }
        }
        CheckBox toggle = new CheckBox(activity);
        toggle.setText("Ativar na próxima inicialização");
        toggle.setChecked(prepared && Stable60Patch.enabled(directory));
        toggle.setEnabled(prepared && imported);
        toggle.setOnCheckedChangeListener((button, checked) -> {
            try {
                Stable60Patch.setEnabled(directory, checked, prepared);
                new AlertDialog.Builder(activity).setMessage("Seleção salva. Feche e abra novamente o aplicativo para aplicar.")
                    .setPositiveButton("OK", null).show();
            } catch (Exception error) {
                button.setOnCheckedChangeListener(null);
                button.setChecked(Stable60Patch.enabled(directory));
                button.setEnabled(false);
                message(activity, error.getMessage());
            }
        });
        layout.addView(toggle);
        Button file = new Button(activity);
        file.setText("IMPORTAR MOD (.PCHTXT)");
        Button paste = new Button(activity);
        paste.setText("COLAR CÓDIGO DO MOD");
        layout.addView(file);
        layout.addView(paste);
        ScrollView scroll = new ScrollView(activity);
        scroll.addView(layout);
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle("MODS")
            .setView(scroll).setNegativeButton("FECHAR", null).create();
        file.setOnClickListener(view -> {
            dialog.dismiss();
            Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            picker.setType("*/*");
            picker.addCategory(Intent.CATEGORY_OPENABLE);
            activity.startActivityForResult(picker, PICK_FILE);
        });
        paste.setOnClickListener(view -> {
            dialog.dismiss();
            EditText input = new EditText(activity);
            input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
            input.setMinLines(5);
            input.setMaxLines(8);
            new AlertDialog.Builder(activity).setTitle("Colar PCHTXT").setView(input)
                .setNegativeButton("CANCELAR", null)
                .setPositiveButton("IMPORTAR", (d, w) -> {
                    try {
                        Stable60Patch.importPatch(directory, input.getText().toString());
                        show(activity, prepared);
                    } catch (Exception error) { message(activity, error.getMessage()); }
                }).show();
        });
        dialog.show();
    }

    public static void importFile(Activity activity, Uri uri) {
        new Thread(() -> {
            String error = null;
            try (InputStream stream = activity.getContentResolver().openInputStream(uri)) {
                if (stream == null) throw new java.io.IOException("Não consegui abrir o mod.");
                Stable60Patch.importPatch(new File(activity.getFilesDir(), "mods"), Stable60Patch.read(stream));
            } catch (Exception failure) {
                error = failure.getMessage() == null ? failure.toString() : failure.getMessage();
            }
            String result = error;
            activity.runOnUiThread(() -> message(activity, result == null ?
                "Stable 60fps v2 importado. Abra MODS para ativar; é necessário ter a biblioteca compatível." : result));
        }, "LASRecompImportMod").start();
    }

    private static void message(Activity activity, String text) {
        if (!activity.isFinishing() && !activity.isDestroyed())
            new AlertDialog.Builder(activity).setMessage(text).setPositiveButton("OK", null).show();
    }
}
