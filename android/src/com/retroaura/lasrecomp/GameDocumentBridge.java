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

    public static int openReadFd(Context context, Uri tree, String relativePath) throws IOException {
        if (!hasPermission(context, tree)) throw new SecurityException("Game folder permission expired");
        Uri document = child(context, tree, relativePath);
        ParcelFileDescriptor descriptor = context.getContentResolver().openFileDescriptor(document, "r");
        if (descriptor == null) throw new FileNotFoundException(relativePath);
        return descriptor.detachFd();
    }
}
