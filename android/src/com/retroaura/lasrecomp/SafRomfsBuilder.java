package com.retroaura.lasrecomp;

import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Stream a Switch RomFS image from SAF documents into a SAF output document.
 * Mirrors runtime/romfs_build.c, without copying the input tree to app storage.
 */
final class SafRomfsBuilder {
    private static final int EMPTY = -1;
    private static final int DATA_START = 0x200;
    private final Context context;
    private final Uri tree;
    private final List<Dir> dirs = new ArrayList<>();
    private final List<Item> files = new ArrayList<>();
    private static final class Dir {
        String name;
        Dir parent;
        List<Dir> children = new ArrayList<>();
        List<Item> items = new ArrayList<>();
        int off;
        Dir(String n, Dir p) { name=n; parent=p; }
    }
    private static final class Item {
        String name;
        Uri uri;
        long size, dataOff;
        int off;
        Dir parent;
        Item(String n, Uri u, long s, Dir p) { name=n; uri=u; size=s; parent=p; }
    }
    SafRomfsBuilder(Context context, Uri tree) { this.context=context; this.tree=tree; }
    private static int align4(int x) { return (x+3)&~3; }
    private static long align16(long x) { return (x+15)&~15L; }
    private static int bucketCount(int n) {
        if (n<3) return 3;
        if (n<19) return n|1;
        while (n%2==0||n%3==0||n%5==0||n%7==0||n%11==0||n%13==0||n%17==0) n++;
        return n;
    }
    private static int hash(int parent, String name) {
        int h=parent ^ 123456789;
        for (byte b : name.getBytes(StandardCharsets.UTF_8))
            h=Integer.rotateRight(h,5) ^ (b & 255);
        return h;
    }
    private void scan(Dir dir, String id, int depth) throws IOException {
        if (depth>32) throw new IOException("RomFS too deep");
        Uri listing=DocumentsContract.buildChildDocumentsUriUsingTree(tree,id);
        String[] columns={DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
                DocumentsContract.Document.COLUMN_SIZE};
        try (Cursor c=context.getContentResolver().query(listing,columns,null,null,null)) {
            if (c==null) throw new IOException("Cannot list RomFS");
            while(c.moveToNext()) {
                String name=c.getString(1), childId=c.getString(0);
                if(name==null||name.startsWith(".")||name.contains("/")||name.contains("\\"))
                    continue;
                if(DocumentsContract.Document.MIME_TYPE_DIR.equals(c.getString(2))) {
                    Dir child=new Dir(name,dir);
                    dir.children.add(child);
                    scan(child,childId,depth+1);
                } else {
                    long size=c.isNull(3)?-1:c.getLong(3);
                    if(size<0) throw new IOException("File size unknown: "+name);
                    dir.items.add(new Item(name,DocumentsContract.buildDocumentUriUsingTree(tree,childId),size,dir));
                }
            }
        }
        dir.children.sort(Comparator.comparing(d->d.name));
        dir.items.sort(Comparator.comparing(f->f.name));
    }
    private void flatten(Dir dir) {
        files.addAll(dir.items);
        dirs.addAll(dir.children);
        for(Dir child:dir.children) flatten(child);
    }
    private static void put32(ByteBuffer b,int offset,int value) { b.putInt(offset,value); }
    private static int siblingDir(Dir d) {
        if(d.parent==null) return EMPTY;
        List<Dir> siblings=d.parent.children;
        int i=siblings.indexOf(d);
        return i+1<siblings.size()?siblings.get(i+1).off:EMPTY;
    }
    private static int siblingFile(Item f) {
        List<Item> siblings=f.parent.items;
        int i=siblings.indexOf(f);
        return i+1<siblings.size()?siblings.get(i+1).off:EMPTY;
    }
    private static void write32(OutputStream out,int[] values) throws IOException {
        ByteBuffer b=ByteBuffer.allocate(values.length*4).order(ByteOrder.LITTLE_ENDIAN);
        for(int value:values)b.putInt(value);
        out.write(b.array());
    }
    private static void zeros(OutputStream out,long count) throws IOException {
        byte[] z=new byte[4096];
        while(count>0){int n=(int)Math.min(count,z.length);out.write(z,0,n);count-=n;}
    }
    void build(Uri romfsDirectory, Uri output) throws IOException {
        Dir root=new Dir("",null);
        scan(root,DocumentsContract.getDocumentId(romfsDirectory),0);
        dirs.add(root);
        flatten(root);
        if(files.isEmpty()) throw new IOException("RomFS contains no files");
        int ds=0,fs=0;
        for(Dir d:dirs) {d.off=ds;ds+=0x18+align4(d.name.getBytes(StandardCharsets.UTF_8).length);}
        for(Item f:files) {f.off=fs;fs+=0x20+align4(f.name.getBytes(StandardCharsets.UTF_8).length);}
        long data=0;
        for(Item f:files) {data=align16(data);f.dataOff=data;data+=f.size;}
        int nd=bucketCount(dirs.size()),nf=bucketCount(files.size());
        int[] db=new int[nd],fb=new int[nf];
        java.util.Arrays.fill(db,EMPTY);java.util.Arrays.fill(fb,EMPTY);
        ByteBuffer dt=ByteBuffer.allocate(ds).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer ft=ByteBuffer.allocate(fs).order(ByteOrder.LITTLE_ENDIAN);
        for(Dir d:dirs) {
            byte[] name=d.name.getBytes(StandardCharsets.UTF_8);
            int parent=d.parent==null?0:d.parent.off;
            int h=Integer.remainderUnsigned(hash(parent,d.name),nd);
            put32(dt,d.off,parent);
            put32(dt,d.off+4,siblingDir(d));
            put32(dt,d.off+8,d.children.isEmpty()?EMPTY:d.children.get(0).off);
            put32(dt,d.off+12,d.items.isEmpty()?EMPTY:d.items.get(0).off);
            put32(dt,d.off+16,db[h]);
            put32(dt,d.off+20,name.length);
            dt.position(d.off+0x18);dt.put(name);
            db[h]=d.off;
        }
        for(Item f:files) {
            byte[] name=f.name.getBytes(StandardCharsets.UTF_8);
            int h=Integer.remainderUnsigned(hash(f.parent.off,f.name),nf);
            put32(ft,f.off,f.parent.off);
            put32(ft,f.off+4,siblingFile(f));
            ft.putLong(f.off+8,f.dataOff);
            ft.putLong(f.off+16,f.size);
            put32(ft,f.off+24,fb[h]);
            put32(ft,f.off+28,name.length);
            ft.position(f.off+0x20);ft.put(name);
            fb[h]=f.off;
        }
        long dh=(DATA_START+data+3)&~3L,dm=dh+4L*nd,fh=dm+ds,fm=fh+4L*nf;
        ByteBuffer header=ByteBuffer.allocate(DATA_START).order(ByteOrder.LITTLE_ENDIAN);
        for(long v:new long[]{0x50,dh,4L*nd,dm,ds,fh,4L*nf,fm,fs,DATA_START})header.putLong(v);
        try(OutputStream out=context.getContentResolver().openOutputStream(output,"wt")) {
            if(out==null) throw new IOException("Cannot create external RomFS");
            out.write(header.array());
            byte[] buffer=new byte[131072];
            long pos=0;
            for(Item f:files) {
                zeros(out,f.dataOff-pos);
                try(InputStream in=context.getContentResolver().openInputStream(f.uri)) {
                    if(in==null) throw new IOException("Cannot read "+f.name);
                    long left=f.size;
                    while(left>0) {
                        int n=in.read(buffer,0,(int)Math.min(buffer.length,left));
                        if(n<0) throw new IOException("Truncated file "+f.name);
                        if(n==0) continue;
                        out.write(buffer,0,n);left-=n;
                    }
                }
                pos=f.dataOff+f.size;
            }
            zeros(out,dh-DATA_START-pos);
            write32(out,db);out.write(dt.array());write32(out,fb);out.write(ft.array());
            out.flush();
        }
    }
}
