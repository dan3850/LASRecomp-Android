package com.retroaura.lasrecomp;

import android.content.ContentResolver;
import android.content.Context;
import android.content.UriPermission;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.database.Cursor;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * SAF bridge for native game file reads. A returned descriptor is seekable
 * only when the document provider supports seeking; callers must check lseek.
 * Ownership of the detached descriptor passes to the native caller.
 */
public final class GameDocumentBridge {
    private GameDocumentBridge() {}

    public static boolean hasPermission(Context context, Uri tree) {
        for (UriPermission permission : context.getContentResolver().getPersistedUriPermissions()) {
            if (permission.isReadPermission() && permission.getUri().equals(tree)) return true;
        }
        return false;
    }

    public static Uri child(Context context, Uri tree, String relativePath) throws IOException {
        if (relativePath == null || relativePath.isEmpty()) throw new IOException("Empty document path");
        String parentId = DocumentsContract.getTreeDocumentId(tree);
        ContentResolver resolver = context.getContentResolver();
        String[] parts = relativePath.split("/", -1);
        for (String part : parts) {
            if (part.isEmpty() || part.equals(".") || part.equals("..") || part.indexOf('\\') >= 0)
                throw new IOException("Invalid document path");
            Uri listing = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
            String nextId = null;
            try (Cursor cursor = resolver.query(listing, new String[] {
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME }, null, null, null)) {
                if (cursor == null) throw new IOException("Cannot enumerate documents");
                while (cursor.moveToNext()) {
                    if (part.equals(cursor.getString(1))) {
                        nextId = cursor.getString(0);
                        break;
                    }
                }
            }
            if (nextId == null) throw new FileNotFoundException(relativePath);
            parentId = nextId;
        }
        return DocumentsContract.buildDocumentUriUsingTree(tree, parentId);
    }

    /**
     * Enumerate original RomFS files without copying their contents.
     * Each record is relative path, tab, byte length. A game-specific virtual
     * storage layer can use this index to translate RomFS offsets into SAF reads.
     */
    public static List<String> indexRomfs(Context context, Uri tree) throws IOException {
        if (!hasPermission(context, tree))
            throw new SecurityException("Game folder permission expired");
        Uri root = child(context, tree, "romfs");
        List<String> files = new ArrayList<>();
        indexDirectory(context.getContentResolver(), tree,
            DocumentsContract.getDocumentId(root), "", 0, files);
        return files;
    }

    private static void indexDirectory(ContentResolver resolver, Uri tree, String parentId,
                                       String prefix, int depth, List<String> files)
            throws IOException {
        if (depth > 48) throw new IOException("RomFS folder depth exceeded");
        Uri listing = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
        String[] projection = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE
        };
        try (Cursor cursor = resolver.query(listing, projection, null, null, null)) {
            if (cursor == null) throw new IOException("Cannot enumerate RomFS documents");
            while (cursor.moveToNext()) {
                String id = cursor.getString(0);
                String name = cursor.getString(1);
                String mime = cursor.getString(2);
                if (name == null || name.isEmpty() || name.equals(".") ||
                    name.equals("..") || name.indexOf('/') >= 0 ||
                    name.indexOf('\\\\') >= 0 || name.indexOf('\\t') >= 0 ||
                    name.indexOf('\\n') >= 0)
                    throw new IOException("Invalid RomFS filename");
                String relative = prefix + name;
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    indexDirectory(resolver, tree, id, relative + "/", depth + 1, files);
                } else {
                    if (cursor.isNull(3) || cursor.getLong(3) < 0)
                        throw new IOException("Missing file size: " + relative);
                    files.add(relative + "\\t" + cursor.getLong(3));
                }
            }
        }
    }

    public static int openReadFd(Context context, Uri tree, String relativePath) throws IOException {
        if (!hasPermission(context, tree)) throw new SecurityException("Game folder permission expired");
        Uri document = child(context, tree, relativePath);
        ParcelFileDescriptor descriptor = context.getContentResolver().openFileDescriptor(document, "r");
        if (descriptor == null) throw new FileNotFoundException(relativePath);
        return descriptor.detachFd();
    }
}
