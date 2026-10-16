package com.retroaura.lasrecomp;

import android.content.ContentResolver;
import android.content.Context;
import android.content.UriPermission;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.database.Cursor;
import android.system.Os;
import android.system.OsConstants;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/** Read-only SAF bridge. No game payload is copied or turned into an image. */
public final class GameDocumentBridge {
    private static final int INDEX_LIMIT = 64 * 1024 * 1024;
    private GameDocumentBridge() {}

    public static boolean hasPermission(Context context, Uri tree) {
        for (UriPermission permission : context.getContentResolver().getPersistedUriPermissions()) {
            if (permission.isReadPermission() && permission.getUri().equals(tree)) return true;
        }
        return false;
    }

    private static boolean validName(String name) {
        return name != null && !name.isEmpty() && !name.equals(".") && !name.equals("..")
            && name.indexOf('/') < 0 && name.indexOf('\\') < 0 && name.indexOf('\t') < 0
            && name.indexOf('\n') < 0 && name.indexOf('\r') < 0 && name.indexOf('\u0000') < 0
            && name.getBytes(StandardCharsets.UTF_8).length <= 255;
    }

    public static Uri child(Context context, Uri tree, String relativePath) throws IOException {
        if (relativePath == null || relativePath.isEmpty()) throw new IOException("Caminho vazio");
        String parentId = DocumentsContract.getTreeDocumentId(tree);
        ContentResolver resolver = context.getContentResolver();
        for (String part : relativePath.split("/", -1)) {
            if (!validName(part)) throw new IOException("Caminho de documento inválido");
            Uri listing = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
            String nextId = null;
            try (Cursor cursor = resolver.query(listing, new String[] {
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME }, null, null, null)) {
                if (cursor == null) throw new IOException("Não foi possível listar a pasta");
                while (cursor.moveToNext()) {
                    if (part.equals(cursor.getString(1))) {
                        if (nextId != null) throw new IOException("Nome duplicado: " + part);
                        nextId = cursor.getString(0);
                    }
                }
            }
            if (nextId == null) throw new FileNotFoundException(relativePath);
            parentId = nextId;
        }
        return DocumentsContract.buildDocumentUriUsingTree(tree, parentId);
    }

    /** IDs are cached as well as paths: random reads do not re-enumerate folders. */
    public static final class RomfsIndex {
        private final Map<String, Uri> documents = new HashMap<>();
        private final Map<String, Long> sizes = new HashMap<>();
        private byte[] manifest;
        private String probePath;
        private long largestSize = -1;
        public byte[] manifest() { return manifest; }
        public int fileCount() { return sizes.size(); }

        public int open(Context context, Uri tree, String path) throws IOException {
            if (!hasPermission(context, tree))
                throw new SecurityException("Permissão da pasta do jogo revogada; selecione a pasta novamente");
            Uri document = documents.get(path);
            Long size = sizes.get(path);
            if (document == null || size == null) throw new FileNotFoundException(path);
            return openSeekable(context, document, path, size);
        }

        public void validateAccess(Context context, Uri tree) throws IOException {
            // Only a descriptor and two bytes are read, even for a multi-GB file.
            // Every other descriptor is validated when first opened by the engine.
            if (probePath == null) throw new IOException("Pasta romfs vazia");
            try (ParcelFileDescriptor fd = ParcelFileDescriptor.adoptFd(open(context, tree, probePath))) {
                if (largestSize > 0) {
                    byte[] one = new byte[1];
                    if (Os.pread(fd.getFileDescriptor(), one, 0, 1, 0) != 1 ||
                        Os.pread(fd.getFileDescriptor(), one, 0, 1, largestSize - 1) != 1)
                        throw new IOException("Arquivo incompleto: " + probePath);
                }
            } catch (android.system.ErrnoException e) {
                throw new IOException("O provedor não permite leitura aleatória: " + probePath, e);
            }
        }
    }

    public static RomfsIndex indexRomfs(Context context, Uri tree) throws IOException {
        if (!hasPermission(context, tree))
            throw new SecurityException("Permissão permanente da pasta do jogo necessária");
        Uri root = child(context, tree, "romfs");
        RomfsIndex index = new RomfsIndex();
        StringBuilder records = new StringBuilder();
        indexDirectory(context.getContentResolver(), tree,
            DocumentsContract.getDocumentId(root), "", 0, index, records);
        if (index.fileCount() == 0) throw new IOException("Nenhum arquivo na pasta romfs");
        index.manifest = records.toString().getBytes(StandardCharsets.UTF_8);
        if (index.manifest.length > INDEX_LIMIT) throw new IOException("Índice RomFS grande demais");
        return index;
    }

    private static void indexDirectory(ContentResolver resolver, Uri tree, String parentId,
                                       String prefix, int depth, RomfsIndex index, StringBuilder records)
            throws IOException {
        if (depth > 48) throw new IOException("Pasta RomFS profunda demais");
        Uri listing = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
        String[] projection = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE
        };
        try (Cursor cursor = resolver.query(listing, projection, null, null, null)) {
            if (cursor == null) throw new IOException("Não foi possível listar a RomFS");
            while (cursor.moveToNext()) {
                String id = cursor.getString(0), name = cursor.getString(1), mime = cursor.getString(2);
                if (!validName(name) || id == null || mime == null)
                    throw new IOException("Nome ou documento RomFS inválido");
                if (name.startsWith(".")) continue; // same rule as romfs_build.c
                String relative = prefix + name;
                if (relative.getBytes(StandardCharsets.UTF_8).length > 4095)
                    throw new IOException("Caminho RomFS longo demais: " + relative);
                Uri document = DocumentsContract.buildDocumentUriUsingTree(tree, id);
                if (index.documents.put(relative, document) != null)
                    throw new IOException("Caminho RomFS duplicado: " + relative);
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    records.append("D\t").append(relative).append('\n');
                    indexDirectory(resolver, tree, id, relative + "/", depth + 1, index, records);
                } else {
                    long size;
                    if (cursor.isNull(3) || cursor.getLong(3) < 0) {
                        // Some local document providers omit COLUMN_SIZE but supply a valid fd stat.
                        try (ParcelFileDescriptor fd = resolver.openFileDescriptor(document, "r")) {
                            size = fd == null ? -1 : fd.getStatSize();
                        }
                    } else size = cursor.getLong(3);
                    if (size < 0) throw new IOException("Tamanho indisponível: " + relative);
                    index.sizes.put(relative, size);
                    records.append("F\t").append(size).append('\t').append(relative).append('\n');
                    if (size > index.largestSize) { index.largestSize = size; index.probePath = relative; }
                }
                if (records.length() > INDEX_LIMIT / 4)
                    throw new IOException("Índice RomFS grande demais");
            }
        }
    }

    private static int openSeekable(Context context, Uri document, String path, long expectedSize)
            throws IOException {
        // try-with-resources also closes a descriptor if validation/detach fails.
        try (ParcelFileDescriptor fd = context.getContentResolver().openFileDescriptor(document, "r")) {
            if (fd == null) throw new FileNotFoundException(path);
            Os.lseek(fd.getFileDescriptor(), 0, OsConstants.SEEK_CUR);
            long actual = fd.getStatSize();
            if (actual >= 0 && expectedSize >= 0 && actual != expectedSize)
                throw new IOException("Tamanho do arquivo mudou: " + path + "; selecione a pasta novamente");
            return fd.detachFd();
        } catch (android.system.ErrnoException e) {
            throw new IOException("Arquivo não permite acesso aleatório; escolha armazenamento local: " + path, e);
        }
    }

    public static int openReadFd(Context context, Uri tree, String relativePath) throws IOException {
        if (!hasPermission(context, tree)) throw new SecurityException("Permissão da pasta do jogo revogada");
        return openSeekable(context, child(context, tree, relativePath), relativePath, -1);
    }
}
