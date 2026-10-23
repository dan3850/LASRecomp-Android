package com.retroaura.lasrecomp;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.DocumentsContract;
import android.provider.Settings;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Arrays;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * Experimental ScarletNX ABI-12 launcher. A signed APK contains the AOT module;
 * ScarletNX reads the user's NSP through source= without extracting ExeFS/RomFS.
 * Does not execute untrusted code from writable external storage.
 */
public final class CastlevaniaSnxBootActivity extends Activity {
    private static final String ID = "01006BB00C6F0000";
    private static final int PICK_NSP = 301;
    private static final int PICK_KEYS = 302;
    private static final int EXPORT_LOG = 303;
    private static final int EXPORT_SHADERS = 304;
    private static final int IMPORT_RYUJINX_BRIDGE = 305;
    private static final int IMPORT_GAME_MODULE = 306;
    private volatile boolean importingModule;
    private TextView status;
    private Uri selectedXci;

    private void message(String value) { status.setText(value); }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        String prior = getPreferences(MODE_PRIVATE).getString("xci", null);
        if (prior != null) selectedXci = Uri.parse(prior);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(16 * getResources().getDisplayMetrics().density);
        content.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Zelda: Link's Awakening — ScarletNX experimental");
        title.setTextSize(22);
        content.addView(title);
        TextView info = new TextView(this);
        info.setText("Selecione seu NSP e suas chaves. Se o modulo do jogo nao estiver no aplicativo, importe o arquivo 01006BB00C6F0000_code.so que voce ja possui.");
        content.addView(info);

        Button chooseXci = new Button(this);
        chooseXci.setText("1. Selecionar NSP");
        chooseXci.setOnClickListener(v -> pick(PICK_NSP));
        content.addView(chooseXci);

        Button chooseKeys = new Button(this);
        chooseKeys.setText("2. Importar prod.keys do meu console");
        chooseKeys.setOnClickListener(v -> pick(PICK_KEYS));
        content.addView(chooseKeys);

        Button permission = new Button(this);
        permission.setText("3. Autorizar leitura direta de arquivos");
        permission.setOnClickListener(v -> requestFilePermission());
        content.addView(permission);

        Button module = new Button(this);
        module.setText("Importar modulo do jogo (.so)");
        module.setOnClickListener(v -> pick(IMPORT_GAME_MODULE));
        content.addView(module);

        Button capture = new Button(this);
        capture.setText(shaderCaptureLabel());
        capture.setOnClickListener(v -> {
            boolean enabled = !getPreferences(MODE_PRIVATE).getBoolean("shader_capture", false);
            getPreferences(MODE_PRIVATE).edit().putBoolean("shader_capture", enabled).apply();
            capture.setText(shaderCaptureLabel());
            message(enabled ? "Captura ativada para a proxima execucao; jogue ate a cena com graficos ausentes."
                    : "Captura de shaders desativada para a proxima execucao.");
        });
        content.addView(capture);

        Button exportShaders = new Button(this);
        exportShaders.setText("Exportar shaders de fragmento (.zip)");
        exportShaders.setOnClickListener(v -> {
            Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("application/zip");
            i.putExtra(Intent.EXTRA_TITLE, "Zelda-shaders-SNXS.zip");
            startActivityForResult(i, EXPORT_SHADERS);
        });
        content.addView(exportShaders);

        // NativeAOT Ryujinx translates live Maxwell shaders, no .snxrbr packs.
        // This gate only diagnoses rejected shaders. The original Vulkan output
        // is intentionally preserved until descriptor/IO compatibility is proven.
        Button nativeProbe = new Button(this);
        nativeProbe.setText(nativeProbeLabel());
        nativeProbe.setOnClickListener(v -> {
            boolean enabled = !getPreferences(MODE_PRIVATE).getBoolean("ryujinx_native_probe", getPackageName().endsWith(".graphics"));
            getPreferences(MODE_PRIVATE).edit()
                    .putBoolean("ryujinx_native_probe", enabled).apply();
            nativeProbe.setText(nativeProbeLabel());
            message(enabled ? "Ryujinx Vulkan: tradutor automatico ligado para shaders rejeitados pelo ScarletNX; fallback seguro."
                    : "Ryujinx Vulkan desligado. Renderizador ScarletNX original.");
        });
        content.addView(nativeProbe);

        Button launch = new Button(this);
        launch.setText("4. Iniciar Zelda pelo ScarletNX");
        launch.setOnClickListener(v -> startGame());
        content.addView(launch);

        Button logs = new Button(this);
        logs.setText("Ver ultimo log");
        logs.setOnClickListener(v -> {
            message("Lendo diagnostico ScarletNX (shaders e Vulkan)...");
            new Thread(() -> {
                String report = readLogs();
                runOnUiThread(() -> message(report));
            }, "snx-log-preview").start();
        });
        content.addView(logs);

        Button export = new Button(this);
        export.setText("Salvar log");
        export.setOnClickListener(v -> {
            Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("text/plain");
            i.putExtra(Intent.EXTRA_TITLE, "Zelda-SNX-boot.txt");
            startActivityForResult(i, EXPORT_LOG);
        });
        content.addView(export);

        status = new TextView(this);
        status.setTextIsSelectable(true);
        status.setText("NSP: " + (selectedXci == null ? "nao selecionado" : selectedXci.toString()));
        content.addView(status);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        setContentView(scroll);
    }

    private void pick(int code) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION |
                   Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(i, code);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        try {
            if (request == PICK_NSP) {
                getContentResolver().takePersistableUriPermission(
                        uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
                selectedXci = uri;
                getPreferences(MODE_PRIVATE).edit().putString("xci", uri.toString()).apply();
                message("NSP selecionado. Agora confira as chaves e a permissao de arquivos.");
            } else if (request == PICK_KEYS) {
                File home = new File(getFilesDir(), "snx-home/.switch");
                if (!home.isDirectory() && !home.mkdirs()) throw new IOException("Nao criou " + home);
                File dest = new File(home, "prod.keys");
                File pending = new File(home, "prod.keys.partial");
                try (InputStream in = getContentResolver().openInputStream(uri);
                     OutputStream out = new FileOutputStream(pending)) {
                    if (in == null) throw new IOException("Documento inacessivel");
                    byte[] bytes = new byte[32768];
                    int n;
                    while ((n = in.read(bytes)) >= 0) {
                        if (n > 0) out.write(bytes, 0, n);
                    }
                }
                if (pending.length() < 100 || (!pending.renameTo(dest)))
                    throw new IOException("Chaves invalidas ou nao foi possivel guardar no diretorio privado");
                message("prod.keys guardado somente no armazenamento privado do app. Nao sera incluido nos logs.");
            } else if (request == IMPORT_GAME_MODULE) {
                if (importingModule) return;
                importingModule = true;
                message("Importando modulo do jogo...");
                new Thread(() -> {
                    try {
                        importGameModule(uri);
                        runOnUiThread(() -> message("Modulo do jogo importado. Pronto para iniciar."));
                    } catch (Exception error) {
                        runOnUiThread(() -> message("Falha importando modulo: " + error.getMessage()));
                    } finally { importingModule = false; }
                }, "snx-module-import").start();
            } else if (request == IMPORT_RYUJINX_BRIDGE) {
                final Uri input = uri;
                message("Importando pack local Ryujinx para a pasta privada do Zelda...");
                new Thread(() -> {
                    try {
                        importRyujinxBridge(input);
                        runOnUiThread(() -> message("Ponte Ryujinx importada. Ative o modo experimental para testar."));
                    } catch (Exception error) {
                        runOnUiThread(() -> message("Falha importando ponte Ryujinx: " + error.getMessage()));
                    }
                }, "snx-ryujinx-import").start();
            } else if (request == EXPORT_SHADERS) {
                final Uri output = uri;
                message("Exportando apenas shaders de fragmento; sem NSP ou chaves...");
                new Thread(() -> {
                    try {
                        int count = exportFragmentShaders(output);
                        runOnUiThread(() -> message("Exportados " + count + " shaders em ZIP. Os dados ficam no arquivo escolhido."));
                    } catch (Exception error) {
                        runOnUiThread(() -> message("Falha exportando shaders: " + error.getMessage()));
                    }
                }, "snx-shader-export").start();
            } else if (request == EXPORT_LOG) {
                final Uri output = uri;
                message("Gerando relatorio completo de falhas de shader...");
                new Thread(() -> {
                    try (OutputStream out = getContentResolver().openOutputStream(output, "w")) {
                        if (out == null) throw new IOException("Nao abriu destino");
                        out.write(readLogs().getBytes(StandardCharsets.UTF_8));
                        runOnUiThread(() -> message("Diagnostico grafico salvo. Envie o TXT para analise."));
                    } catch (Exception error) {
                        runOnUiThread(() -> message("Falha salvando diagnostico: " + error));
                    }
                }, "snx-log-export").start();
            }
        } catch (Exception error) {
            message("Falha: " + error.getMessage());
        }
    }

    private String nativeProbeLabel() {
        return "Ryujinx Vulkan automatico (experimental): " +
               (getPreferences(MODE_PRIVATE).getBoolean("ryujinx_native_probe", getPackageName().endsWith(".graphics"))
                ? "LIGADO" : "DESLIGADO");
    }

    private void importRyujinxBridge(Uri source) throws IOException {
        File directory = new File(getFilesDir(), "snx-games/" + ID);
        makeDir(directory);
        File dest = new File(directory, "ryujinx-bridge.snxrbr");
        File pending = new File(directory, "ryujinx-bridge.partial");
        byte[] magic = new byte[8];
        int count = 0;
        long size = 0;
        try (InputStream in = getContentResolver().openInputStream(source);
             OutputStream out = new FileOutputStream(pending)) {
            if (in == null) throw new IOException("Arquivo nao disponivel");
            byte[] data = new byte[32768];
            int n;
            while ((n = in.read(data)) != -1) {
                if (n == 0) continue;
                size += n;
                if (size > 4 * 1024 * 1024) throw new IOException("Arquivo excede 4 MB");
                out.write(data, 0, n);
            }
        } catch (Exception error) {
            pending.delete();
            if (error instanceof IOException) throw (IOException)error;
            throw new IOException(error);
        }
        try (InputStream in = new java.io.FileInputStream(pending)) {
            if (in.read(magic) != 8 ||
                    !java.util.Arrays.equals(magic, new byte[]{'S','N','X','R','B','0','0','1'}))
                throw new IOException("Nao e um pack Ryujinx valido");
            byte[] number = new byte[4];
            if (in.read(number) != 4) throw new IOException("Pack truncado");
            count = ((number[0] & 255) | ((number[1] & 255) << 8)
                    | ((number[2] & 255) << 16) | ((number[3] & 255) << 24));
        }
        if (count < 5 || count > 32 || size < 1024) {
            pending.delete();
            throw new IOException("Pack incompleto ou numero de shaders incorreto");
        }
        if (!pending.renameTo(dest)) {
            pending.delete();
            throw new IOException("Nao salvou o pack na pasta privada");
        }
    }

    private String shaderCaptureLabel() {
        return "Capturar shaders na proxima execucao: " +
                (getPreferences(MODE_PRIVATE).getBoolean("shader_capture", false) ? "LIGADO" : "DESLIGADO");
    }

    /** Only the captured Maxwell fragment binaries; no dump, savedata or prod.keys. */
    private int exportFragmentShaders(Uri destination) throws IOException {
        File directory = new File(getFilesDir(), "snx-games/" + ID + "/captures/shaders");
        File[] shaders = directory.listFiles((dir, name) ->
                name.matches("[0-9a-fA-F]{16}_4\\.snxs"));
        if (shaders == null || shaders.length == 0)
            throw new IOException("Nenhum .snxs encontrado. Ative a captura, execute o jogo e tente novamente.");
        Arrays.sort(shaders, (a, b) -> a.getName().compareTo(b.getName()));
        if (shaders.length > 8192)
            throw new IOException("Muitos shaders: " + shaders.length);
        OutputStream raw = getContentResolver().openOutputStream(destination, "w");
        if (raw == null) throw new IOException("Nao abriu o destino");
        int count = 0;
        try (ZipOutputStream zip = new ZipOutputStream(raw)) {
            byte[] buffer = new byte[32768];
            for (File file : shaders) {
                if (!file.isFile() || file.length() < 24 || file.length() > 2 * 1024 * 1024)
                    continue;
                zip.putNextEntry(new ZipEntry("shaders/" + file.getName()));
                try (InputStream in = new java.io.FileInputStream(file)) {
                    int n;
                    while ((n = in.read(buffer)) != -1) zip.write(buffer, 0, n);
                }
                zip.closeEntry();
                count++;
            }
        }
        return count;
    }

    private void requestFilePermission() {
        if (Build.VERSION.SDK_INT < 30) {
            message("Este modo direto requer Android 11 ou posterior.");
            return;
        }
        if (Environment.isExternalStorageManager()) {
            message("Acesso direto ja autorizado.");
            return;
        }
        try {
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:" + getPackageName())));
        } catch (Exception ignored) {
            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        }
    }

    private File directXciPath() throws Exception {
        if (selectedXci == null) throw new IOException("Selecione seu NSP.");
        if (Build.VERSION.SDK_INT < 30 || !Environment.isExternalStorageManager())
            throw new IOException("Autorize o acesso a todos os arquivos.");
        String id = DocumentsContract.getDocumentId(selectedXci);
        if (!id.startsWith("primary:")) throw new IOException("O NSP deve estar na memoria interna principal.");
        String relative = id.substring("primary:".length());
        if (relative.isEmpty() || relative.startsWith("/") ||
                relative.contains("\\") || relative.indexOf(':') >= 0 ||
                relative.indexOf((char) 0) >= 0)
            throw new IOException("Caminho NSP invalido");
        for (String part : relative.split("/", -1)) {
            if (part.isEmpty() || part.equals(".") || part.equals(".."))
                throw new IOException("Caminho NSP inseguro");
        }
        File root = Environment.getExternalStorageDirectory().getCanonicalFile();
        File xci = new File(root, relative).getCanonicalFile();
        if (!xci.getPath().startsWith(root.getPath() + File.separator) ||
                !xci.isFile() || !xci.canRead() ||
                !xci.getName().toLowerCase(Locale.ROOT).endsWith(".xci"))
            throw new IOException("NSP nao encontrado ou sem acesso de leitura: " + xci);
        return xci;
    }

    private static void makeDir(File dir) throws IOException {
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Falha criando: " + dir);
    }

    private File importedGameModule() {
        return new File(getFilesDir(), "snx-modules/" + ID + "_code.so");
    }

    private void importGameModule(Uri source) throws Exception {
        File destination = importedGameModule();
        makeDir(destination.getParentFile());
        File pending = new File(destination.getPath() + ".partial");
        if (pending.exists() && !pending.delete()) throw new IOException("Importacao anterior ocupada");
        try {
            try (InputStream in = getContentResolver().openInputStream(source);
                 FileOutputStream out = new FileOutputStream(pending)) {
                if (in == null) throw new IOException("Documento inacessivel");
                // Android 14+: mark the file read-only BEFORE writing through
                // the already-open descriptor; never execute from shared storage.
                Os.chmod(pending.getAbsolutePath(), 0444);
                byte[] bytes = new byte[1024 * 1024];
                long total = 0;
                int count;
                while ((count = in.read(bytes)) != -1) {
                    total += count;
                    if (total > 2L * 1024 * 1024 * 1024) throw new IOException("Modulo grande demais");
                    out.write(bytes, 0, count);
                }
                out.getFD().sync();
            }
            byte[] header = new byte[64];
            try (FileInputStream in = new FileInputStream(pending)) {
                int got = 0, count;
                while (got < header.length && (count = in.read(header, got, header.length - got)) > 0) got += count;
                if (got != 64 || header[0] != 0x7f || header[1] != 'E' || header[2] != 'L' || header[3] != 'F' ||
                    header[4] != 2 || header[5] != 1 || header[16] != 3 || header[17] != 0 ||
                    (header[18] & 255) != 183 || header[19] != 0)
                    throw new IOException("Selecione o _code.so ARM64 recompilado do Zelda");
            }
            Os.rename(pending.getAbsolutePath(), destination.getAbsolutePath());
        } finally { if (pending.exists()) pending.delete(); }
    }

    private static void linkLibrary(File link, File library) throws Exception {
        String previous = null;
        try { previous = Os.readlink(link.getAbsolutePath()); }
        catch (ErrnoException error) {
            if (error.errno != OsConstants.ENOENT) throw error;
        }
        if (previous != null && !previous.equals(library.getAbsolutePath())) {
            if (!link.delete()) throw new IOException("Nao atualizou modulo antigo");
            previous = null;
        }
        if (previous == null) Os.symlink(library.getAbsolutePath(), link.getAbsolutePath());
        if (!library.getAbsolutePath().equals(Os.readlink(link.getAbsolutePath())))
            throw new IOException("Link nativo nao corresponde ao modulo do APK");
    }

    private void startGame() {
        try {
            if (importingModule) throw new IOException("Aguarde a importacao do modulo");
            File xci = directXciPath();
            File keys = new File(getFilesDir(), "snx-home/.switch/prod.keys");
            if (!keys.isFile() || keys.length() < 100)
                throw new IOException("Importe primeiro seu prod.keys.");
            File nativeDir = new File(getApplicationInfo().nativeLibraryDir);
            File module = new File(nativeDir, "libcastlevania_snx.so");
            if (!module.isFile()) module = importedGameModule();
            File runtime = new File(nativeDir, "libscarletnx.so");
            if (!runtime.isFile() || !module.isFile())
                throw new IOException("Importe o modulo do jogo (_code.so) antes de iniciar.");
            File folder = new File(new File(getFilesDir(), "snx-games"), ID);
            File data = new File(folder, ID + "_data");
            makeDir(folder);
            makeDir(data);
            // This is the source= mode: there must be NO extracted exefs/romfs
            // overlay in the data directory. The pinned ScarletNX reads the NSP.
            if (new File(data, "exefs").exists() || new File(data, "romfs").exists())
                throw new IOException("Diretorio contem extracao antiga. Nao misturar com source=.");
            linkLibrary(new File(folder, ID + "_code.so"), module);
            File state = new File(folder, "state");
            File cache = new File(folder, "cache");
            File config = new File(folder, "config");
            makeDir(state); makeDir(cache); makeDir(config);
            String settings = "state=" + state.getAbsolutePath() + "\n" +
                              "cache=" + cache.getAbsolutePath() + "\n" +
                              "config=" + config.getAbsolutePath() + "\n";
            try (FileOutputStream out = new FileOutputStream(new File(folder, ID + ".folders"))) {
                out.write(settings.getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            message("Iniciando ScarletNX... Se fechar, abra Ver ultimo log.");
            Intent intent = new Intent(this, MarioSnxGameActivity.class);
            intent.putExtra("snx_game_base", new File(folder, ID).getAbsolutePath());
            intent.putExtra("snx_source_dump", xci.getAbsolutePath());
            intent.putExtra("snx_shader_captures", getPreferences(MODE_PRIVATE).getBoolean("shader_capture", false));
            intent.putExtra("snx_ryujinx_native_probe", getPreferences(MODE_PRIVATE).getBoolean("ryujinx_native_probe", getPackageName().endsWith(".graphics")));
            startActivity(intent);
        } catch (Exception error) {
            message("Nao iniciou: " + error);
        }
    }

    private String readLogs() {
        // Never export only the last 60 KB: early shader failures explain
        // missing objects and would otherwise disappear from the report.
        return ScarletNxLogReport.build(getFilesDir(), ID);
    }
}
