// fsp-srv: RomFS as a raw storage image, save data and SD card backed by host directories.
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../hle.h"
#include "../rando.h"
#include "../ipc.h"
#include "../romfs_virtual.h"

#define FS_PATH_NOT_FOUND MAKE_RESULT(2, 1)
#define FS_PATH_EXISTS MAKE_RESULT(2, 2)
#define FS_TARGET_LOCKED MAKE_RESULT(2, 7)
#define FS_NOT_EMPTY MAKE_RESULT(2, 8)

const char *g_save_dir = "save";
static int romfs_fd = -1;
static RomfsVirtual *virtual_romfs;
static uint64_t romfs_size;
static bool romfs_mounted;
static pthread_mutex_t romfs_mount_lock = PTHREAD_MUTEX_INITIALIZER;

// Common base for the legacy image and the external directory. Randomizer
// tables and IStorage must use this rather than bypassing the virtual backend.
static ssize_t romfs_base_read(int fd, void *dst, size_t size, uint64_t off) {
    if (off > romfs_size || size > romfs_size - off || size > (size_t)SSIZE_MAX) {
        errno = EINVAL; return -1;
    }
    if (virtual_romfs) return romfs_virtual_read(virtual_romfs, dst, size, off);
    size_t done = 0;
    while (done < size) {
        ssize_t n = pread(fd, (uint8_t *)dst + done, size - done, (off_t)(off + done));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { if (!n) errno = EIO; return -1; }
        done += (size_t)n;
    }
    return (ssize_t)done;
}

// ------------------------------------------------------------------ RomFS file index (offset -> path)
typedef struct { uint64_t start, size; char *path; int fd; const uint8_t *mem; } Overlay;
// in-image patches (copies of RomFS tables with changes): header, dir meta, file hash, file meta
typedef struct { uint64_t off, size; uint8_t *data; } Patch;
static Patch patches[8];
static int npatches;
static Overlay *ov;
static int ov_n, ov_cap;
static uint8_t *ov_meta;
static uint64_t ov_meta_off, ov_meta_size, ov_end;
static bool overlay_reserve(void) {
    if (ov_n < ov_cap) return true;
    int capacity = ov_cap ? ov_cap * 2 : 256;
    Overlay *grown = realloc(ov, sizeof *ov * capacity);
    if (!grown) return false;
    ov = grown; ov_cap = capacity;
    return true;
}
// Lets the runtime see which game files are being streamed (e.g. which level is loading).
typedef struct { uint64_t off, size; char *path; uint32_t meta; } RomFile;
static RomFile *rom_files;
static int rom_nfiles;
static uint64_t rom_data_off;

// Reboot: the next seed builds its own index / overlay when the game opens the RomFS again.
RT_ON_RESET(fs_reset) {
    for (int i = 0; i < ov_n; i++) {
        if (ov[i].fd >= 0) close(ov[i].fd);
        free(ov[i].path);
        free((void *)ov[i].mem);
    }
    for (int i = 0; i < npatches; i++) if (patches[i].data != ov_meta) free(patches[i].data);
    free(ov_meta);
    for (int i = 0; i < rom_nfiles; i++) free(rom_files[i].path);
    free(ov), free(rom_files);
    ov = NULL, ov_n = ov_cap = 0;
    ov_meta = NULL, ov_meta_off = ov_meta_size = ov_end = 0;
    npatches = 0;
    rom_files = NULL, rom_nfiles = 0, rom_data_off = 0;
    if (romfs_fd >= 0) close(romfs_fd);
    romfs_fd = -1;
    romfs_virtual_close(virtual_romfs);
    virtual_romfs = NULL;
    romfs_size = 0;
    romfs_mounted = false;
    g_save_dir = "save";
}

static int rom_cmp(const void *a, const void *b) {
    const RomFile *x = a, *y = b;
    return x->off < y->off ? -1 : x->off > y->off;
}

static bool rom_dir_path(const uint8_t *dmeta, uint32_t dsize, uint32_t dir, char *out, size_t cap) {
    uint32_t parts[49];
    unsigned n = 0;
    while (dir != 0) {
        if (n == 49 || dir > dsize || dsize - dir < 0x18) return false;
        uint32_t parent, len;
        memcpy(&parent, dmeta + dir, 4);
        memcpy(&len, dmeta + dir + 0x14, 4);
        if (len > 255 || len > dsize - dir - 0x18) return false;
        parts[n++] = dir;
        dir = parent;
    }
    size_t used = 0;
    for (unsigned i = n; i > 0; i--) {
        uint32_t pos = parts[i - 1], len;
        memcpy(&len, dmeta + pos + 0x14, 4);
        if (used + len + 1 >= cap) return false;
        memcpy(out + used, dmeta + pos + 0x18, len);
        used += len; out[used++] = '/';
    }
    out[used] = 0;
    return true;
}

// ---- files a seed ADDS (names the game's RomFS doesn't have: generated dungeon cells...). The game parses the
// RomFS tables itself, so they're extended: a copy of the file-meta table with the new entries appended (linked
// into their directory's file list and the name hash buckets) is placed past the end of the image, the header,
// directory table and hash table are patched to match. New files must go into existing directories.
static uint32_t romfs_hash(uint32_t parent, const char *name, uint32_t len) {
    uint32_t hash = parent ^ 123456789;
    for (uint32_t i = 0; i < len; i++) { hash = (hash >> 5) | (hash << 27); hash ^= (uint8_t)name[i]; }
    return hash;
}

static int path_cmp(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

typedef struct { char rel[1024]; char host[1200]; uint64_t size; } NewFile;

static void walk_new(const char *root, const char *rel, char **known, int nknown, NewFile **out, int *n, int *cap) {
    char dirp[1200];
    snprintf(dirp, sizeof dirp, "%s/%s", root, rel);
    DIR *d = opendir(dirp);
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        char r2[1024], h2[1200];
        snprintf(r2, sizeof r2, "%s%s%s", rel, rel[0] ? "/" : "", e->d_name);
        snprintf(h2, sizeof h2, "%s/%s", root, r2);
        struct stat sb;
        if (stat(h2, &sb)) continue;
        if (S_ISDIR(sb.st_mode)) { walk_new(root, r2, known, nknown, out, n, cap); continue; }
        const char *key = r2;
        if (bsearch(&key, known, nknown, sizeof *known, path_cmp)) continue;  // replaces an existing file
        if (*n == *cap) { *cap = *cap ? *cap * 2 : 64; *out = realloc(*out, sizeof **out * *cap); }
        strlcpy((*out)[*n].rel, r2, sizeof (*out)[*n].rel);
        strlcpy((*out)[*n].host, h2, sizeof (*out)[*n].host);
        (*out)[*n].size = (uint64_t)sb.st_size;
        (*n)++;
    }
    closedir(d);
}

// directory entry offset for "a/b/c" (NULL-terminated walk from the root, offset 0), -1 if missing
static int64_t dir_lookup(const uint8_t *dm, uint64_t dsz, const char *path) {
    uint32_t cur = 0;
    char buf[1024];
    strlcpy(buf, path, sizeof buf);
    for (char *tok = strtok(buf, "/"); tok; tok = strtok(NULL, "/")) {
        uint32_t child;
        memcpy(&child, dm + cur + 8, 4);
        while (child != 0xFFFFFFFFu && child + 0x18 <= dsz) {
            uint32_t nl;
            memcpy(&nl, dm + child + 0x14, 4);
            if (nl == strlen(tok) && !memcmp(dm + child + 0x18, tok, nl)) break;
            memcpy(&child, dm + child + 4, 4);
        }
        if (child == 0xFFFFFFFFu || child + 0x18 > dsz) return -1;
        cur = child;
    }
    return cur;
}

static bool add_new_files(int fd, const uint64_t *h, const uint8_t *dmeta, uint64_t dsz, uint64_t fsz) {
    const char *seed = rando_seed_dir();
    if (!seed) return true;
    uint8_t *dcopy = NULL, *hcopy = NULL, *head = NULL, *tmp = NULL, *meta = NULL;
    char root[1100];
    snprintf(root, sizeof root, "%s/romfs", seed);
    char **known = malloc(sizeof *known * rom_nfiles);
    if (!known) return false;
    for (int i = 0; i < rom_nfiles; i++) known[i] = rom_files[i].path;
    qsort(known, rom_nfiles, sizeof *known, path_cmp);
    NewFile *nf = NULL;
    int n = 0, cap = 0;
    walk_new(root, "", known, rom_nfiles, &nf, &n, &cap);
    free(known);
    if (!n) { free(nf); return true; }
    RomFile *grown = realloc(rom_files, sizeof(RomFile) * (rom_nfiles + n));
    if (!grown) goto fail;
    rom_files = grown;
    uint64_t hoff = h[5], hsz = h[6];
    dcopy = malloc(dsz); hcopy = malloc(hsz); head = malloc(0x50);
    if (!dcopy || !hcopy || !head) goto fail;
    memcpy(dcopy, dmeta, dsz);
    if (romfs_base_read(fd, hcopy, hsz, hoff) != (ssize_t)hsz ||
        romfs_base_read(fd, head, 0x50, 0) != 0x50) goto fail;
    // the file-meta table to extend: the override-patched copy if there is one
    const uint8_t *base_meta = ov_meta;
    if (!base_meta) {
        tmp = malloc(fsz);
        if (!tmp || romfs_base_read(fd, tmp, fsz, h[7]) != (ssize_t)fsz) goto fail;
        base_meta = tmp;
    }
    uint64_t extra = 0;
    for (int i = 0; i < n; i++) {
        const char *name = strrchr(nf[i].rel, '/');
        name = name ? name + 1 : nf[i].rel;
        extra += 0x20 + ((strlen(name) + 3) & ~3u);
    }
    uint64_t nsz = fsz + extra;
    meta = calloc(1, nsz);
    if (!meta) goto fail;
    memcpy(meta, base_meta, fsz);
    free(tmp); tmp = NULL;
    if (!ov_end) {
        ov_end = (romfs_size + 0xF) & ~0xFull;
    }
    uint64_t meta_at = ov_end;  // the new table first, then the new files' data
    uint64_t data_at = (meta_at + nsz + 0xF) & ~0xFull;
    uint32_t nb = (uint32_t)(hsz / 4);
    uint64_t o = fsz;
    int added = 0;
    for (int i = 0; i < n; i++) {
        char dirp[1024];
        strlcpy(dirp, nf[i].rel, sizeof dirp);
        char *slash = strrchr(dirp, '/');
        const char *name = slash ? slash + 1 : nf[i].rel;
        if (slash) *slash = 0; else dirp[0] = 0;
        int64_t dir = dir_lookup(dcopy, dsz, dirp);
        if (dir < 0) { LOG("[fs] seed file %s: directory not in the game's RomFS, skipped\n", nf[i].rel); continue; }
        uint32_t nl = (uint32_t)strlen(name), d32 = (uint32_t)dir, entry = (uint32_t)o, child;
        memcpy(&child, dcopy + dir + 0xC, 4);  // dir's first file -> becomes our sibling
        uint64_t rel = data_at - rom_data_off, size = nf[i].size;
        uint32_t bucket = romfs_hash(d32, name, nl) % nb, prev;
        memcpy(&prev, hcopy + 4 * bucket, 4);
        memcpy(meta + o, &d32, 4);
        memcpy(meta + o + 4, &child, 4);
        memcpy(meta + o + 8, &rel, 8);
        memcpy(meta + o + 0x10, &size, 8);
        memcpy(meta + o + 0x18, &prev, 4);
        memcpy(meta + o + 0x1C, &nl, 4);
        memcpy(meta + o + 0x20, name, nl);
        memcpy(dcopy + dir + 0xC, &entry, 4);
        memcpy(hcopy + 4 * bucket, &entry, 4);
        o += 0x20 + ((nl + 3) & ~3u);
        if (!overlay_reserve()) goto fail;
        ov[ov_n++] = (Overlay){data_at, size, strdup(nf[i].host), -1, NULL};
        rom_files[rom_nfiles++] = (RomFile){data_at, size, strdup(nf[i].rel), entry};
        data_at = (data_at + size + 0xF) & ~0xFull;
        added++;
    }
    // the new table goes before the new data (keep the overlay list sorted by start)
    if (!overlay_reserve()) goto fail;
    memmove(ov + (ov_n - added) + 1, ov + (ov_n - added), sizeof *ov * added);
    ov[ov_n - added] = (Overlay){meta_at, nsz, NULL, -1, meta};
    meta = NULL;
    ov_n++;
    ov_end = data_at;
    uint64_t fmeta_off = meta_at, fmeta_size = o;
    memcpy(head + 7 * 8, &fmeta_off, 8);
    memcpy(head + 8 * 8, &fmeta_size, 8);
    patches[npatches++] = (Patch){0, 0x50, head};
    patches[npatches++] = (Patch){h[3], dsz, dcopy};
    patches[npatches++] = (Patch){hoff, hsz, hcopy};
    LOG("[fs] randomizer: %d new romfs files\n", added);
    free(nf);
    return true;
fail:
    free(nf); free(dcopy); free(hcopy); free(head); free(tmp); free(meta);
    return false;
}

static bool rom_index(int fd) {
    uint64_t h[10];
    uint8_t *dmeta = NULL, *fmeta = NULL;
    if (romfs_base_read(fd, h, sizeof h, 0) != (ssize_t)sizeof h) goto fail;
    if (h[0] != 0x50 || h[9] < 0x50 || h[9] > romfs_size) goto fail;
    for (int i = 1; i <= 7; i += 2)
        if (h[i] < 0x50 || h[i] > romfs_size || h[i + 1] > romfs_size - h[i] ||
            h[i + 1] > (64u << 20)) goto fail;
    if (h[4] < 0x18 || h[8] < 0x20 || !h[2] || !h[6] || (h[2] & 3) || (h[6] & 3)) goto fail;
    // header: size, dir hash (off,size), dir meta (off,size), file hash (off,size), file meta (off,size), data off
    uint64_t doff = h[3], dsz = h[4], foff = h[7], fsz = h[8];
    rom_data_off = h[9];
    dmeta = malloc(dsz); fmeta = malloc(fsz);
    if (!dmeta || !fmeta || romfs_base_read(fd, dmeta, dsz, doff) != (ssize_t)dsz ||
        romfs_base_read(fd, fmeta, fsz, foff) != (ssize_t)fsz) goto fail;
    int cap = 4096;
    rom_files = malloc(sizeof(RomFile) * cap);
    if (!rom_files) goto fail;
    for (uint64_t o = 0; o + 0x20 <= fsz;) {
        uint32_t parent, namelen;
        uint64_t data, size;
        memcpy(&parent, fmeta + o, 4);
        memcpy(&data, fmeta + o + 8, 8);
        memcpy(&size, fmeta + o + 0x10, 8);
        memcpy(&namelen, fmeta + o + 0x1C, 4);
        char dir[4096], name[256];
        if (namelen > 255 || namelen > fsz - o - 0x20 ||
            data > romfs_size - rom_data_off || size > romfs_size - rom_data_off - data ||
            !rom_dir_path(dmeta, (uint32_t)dsz, parent, dir, sizeof dir)) goto fail;
        uint32_t nl = namelen;
        memcpy(name, fmeta + o + 0x20, nl);
        name[nl] = 0;
        if (rom_nfiles == cap) {
            cap *= 2;
            RomFile *grown = realloc(rom_files, sizeof(RomFile) * cap);
            if (!grown) goto fail;
            rom_files = grown;
        }
        char *path = malloc(strlen(dir) + nl + 1);
        if (!path) goto fail;
        strcpy(path, dir);
        strcat(path, name);
        rom_files[rom_nfiles++] = (RomFile){rom_data_off + data, size, path, (uint32_t)o};
        o += 0x20 + ((namelen + 3) & ~3u);
    }
    // Randomizer seed: replacement files are served from the seed folder. The file-meta table is patched
    // (in a copy) to point them at data appended past the end of the image; reads there go to host files.
    for (int i = 0; i < rom_nfiles; i++) {
        char host[1200];
        if (!rando_romfs_override(rom_files[i].path, host, sizeof host)) continue;
        struct stat sb;
        if (stat(host, &sb)) continue;
        if (!ov_meta) {
            ov_meta = malloc(fsz);
            if (!ov_meta) goto fail;
            memcpy(ov_meta, fmeta, fsz);
            ov_meta_off = foff;
            ov_meta_size = fsz;
            ov_end = (romfs_size + 0xF) & ~0xFull;
        }
        uint64_t rel = ov_end - rom_data_off, size = (uint64_t)sb.st_size;
        memcpy(ov_meta + rom_files[i].meta + 8, &rel, 8);
        memcpy(ov_meta + rom_files[i].meta + 0x10, &size, 8);
        if (!overlay_reserve()) goto fail;
        ov[ov_n].start = ov_end;
        ov[ov_n].size = size;
        ov[ov_n].path = strdup(host);
        ov[ov_n].fd = -1;
        ov[ov_n].mem = NULL;
        ov_n++;
        ov_end = (ov_end + size + 0xF) & ~0xFull;
    }
    if (ov_n) LOG("[fs] randomizer: %d romfs files replaced\n", ov_n);
    if (ov_meta) { patches[npatches++] = (Patch){ov_meta_off, ov_meta_size, ov_meta}; }
    if (!add_new_files(fd, h, dmeta, dsz, fsz)) goto fail;
    qsort(rom_files, rom_nfiles, sizeof *rom_files, rom_cmp);
    free(dmeta);
    free(fmeta);
    LOG("[fs] romfs index: %d files\n", rom_nfiles);
    return true;
fail:
    free(dmeta); free(fmeta);
    LOG("[fs] invalid or unreadable RomFS metadata\n");
    return false;
}

// Virtual RomFS image read: original bytes, with the patched file table and appended replacement files.
static ssize_t romfs_read(int fd, uint8_t *dst, uint64_t size, uint64_t off) {
    if (!ov_n) return romfs_base_read(fd, dst, (size_t)size, off);
    uint64_t done = 0;
    while (done < size) {
        uint64_t o = off + done, n = size - done;
        if (o >= ov[0].start) {
            int i = 0;
            while (i < ov_n && o >= ov[i].start + ((ov[i].size + 0xF) & ~0xFull)) i++;
            if (i == ov_n || o < ov[i].start) {
                if (i < ov_n && n > ov[i].start - o) n = ov[i].start - o;
                memset(dst + done, 0, (size_t)n); // synthetic alignment only
            } else {
                uint64_t in = o - ov[i].start;
                uint64_t avail = ((ov[i].size + 0xF) & ~0xFull) - in;
                if (n > avail) n = avail;
                size_t data = in < ov[i].size ? (size_t)(n < ov[i].size - in ? n : ov[i].size - in) : 0;
                if (data && ov[i].mem) memcpy(dst + done, ov[i].mem + in, data);
                else if (data) {
                    if (ov[i].fd < 0) ov[i].fd = open(ov[i].path, O_RDONLY);
                    if (ov[i].fd < 0) return -1;
                    size_t read_bytes = 0;
                    while (read_bytes < data) {
                        ssize_t got = pread(ov[i].fd, dst + done + read_bytes, data - read_bytes, (off_t)(in + read_bytes));
                        if (got < 0 && errno == EINTR) continue;
                        if (got <= 0) { if (!got) errno = EIO; return -1; }
                        read_bytes += (size_t)got;
                    }
                }
                if (data < n) memset(dst + done + data, 0, (size_t)n - data);
            }
        } else {
            if (n > ov[0].start - o) n = ov[0].start - o;
            size_t data = o < romfs_size ? (size_t)(n < romfs_size - o ? n : romfs_size - o) : 0;
            if (data && romfs_base_read(fd, dst + done, data, o) != (ssize_t)data) return -1;
            if (data < n) memset(dst + done + data, 0, (size_t)n - data);
            for (int k = 0; k < npatches; k++) {
                uint64_t a = o > patches[k].off ? o : patches[k].off;
                uint64_t b = o + n < patches[k].off + patches[k].size ? o + n : patches[k].off + patches[k].size;
                if (a < b) memcpy(dst + done + (a - o), patches[k].data + (a - patches[k].off), (size_t)(b - a));
            }
        }
        done += n;
    }
    return (ssize_t)done;
}

// Path of the RomFS file containing image offset `off` (NULL if none).
const char *romfs_file_at(uint64_t off) {
    int lo = 0, hi = rom_nfiles - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (off < rom_files[mid].off) hi = mid - 1;
        else if (off >= rom_files[mid].off + rom_files[mid].size) lo = mid + 1;
        else return rom_files[mid].path;
    }
    return NULL;
}

void romfs_file_read_hook(const char *path);

// ------------------------------------------------------------------ IStorage (raw RomFS image)
typedef struct { int fd; uint64_t size; } Storage;

static void storage(Service *s, IpcReq *req, IpcResp *resp) {
    Storage *st = s->state;
    switch (req->cmd) {
    case 0: {  // Read(offset, size) -> B buffer
        uint64_t off = IN(uint64_t, 0), size = IN(uint64_t, 8);
        IpcBuf *b = out_buf(req, 0);
        uint64_t limit = ov_n ? ov_end : st->size;
        if (!b || size > b->size || size > (uint64_t)SSIZE_MAX || off > limit || size > limit - off) {
            resp->result = MAKE_RESULT(2, 6001); break;
        }
        ssize_t n = romfs_read(st->fd, (uint8_t *)(uintptr_t)b->addr, size, off);
        if (n < 0 || (uint64_t)n != size) {
            LOG("[fs] storage read failed at %llx: %s\n", off, strerror(errno));
            resp->result = MAKE_RESULT(2, 4000);
            break;
        }
        {
            const char *path = romfs_file_at(off);
            static const char *last;
            if (path && path != last) {
                last = path;
                if (getenv("LARECOMP_LOG_FILES")) LOG("[fs] read %s\n", path);
                romfs_file_read_hook(path);
            }
        }
        static uint64_t reads, bytes;
        reads++;
        bytes += size;
        if ((reads & (reads - 1)) == 0) LOG("[fs] romfs reads: %llu (%llu KB)\n", reads, bytes >> 10);
        break;
    }
    case 4: OUT(uint64_t, 0) = ov_n ? ov_end : st->size; resp_size(resp, 8); break;  // GetSize
    default: LOG("[fs] IStorage cmd %u (ok)\n", req->cmd);
    }
}

#ifdef __ANDROID__
static int open_external_romfs_file(void *context, const char *relative) {
    (void)context;
    extern int lasrecomp_external_open(const char *relative_path);
    char path[4102];
    if (snprintf(path, sizeof path, "romfs/%s", relative) >= (int)sizeof path) { errno = ENAMETOOLONG; return -1; }
    return lasrecomp_external_open(path);
}
#endif

static Service *open_romfs_storage(void) {
    pthread_mutex_lock(&romfs_mount_lock);
    if (!romfs_mounted) {
        char path[1100];
#ifdef __ANDROID__
        // Explicit directory selection takes precedence over any older local image.
        // romfs/ need not exist locally, so use its parent for the marker.
        snprintf(path, sizeof path, "%s", g_romfs_dir);
        char *slash = strrchr(path, '/');
        if (slash) *slash = 0; else strcpy(path, ".");
        size_t root_len = strlen(path);
        snprintf(path + root_len, sizeof path - root_len, "/.external-romfs-directory");
        if (access(path, F_OK) == 0) {
            extern int lasrecomp_external_romfs_manifest(char **out, size_t *length);
            char *manifest = NULL, why[384] = "";
            size_t length = 0;
            if (lasrecomp_external_romfs_manifest(&manifest, &length) < 0) {
                LOG("[fs] cannot enumerate external RomFS: %s\n", strerror(errno));
                free(manifest); goto failed;
            }
            virtual_romfs = romfs_virtual_create(manifest, length, open_external_romfs_file, NULL, why, sizeof why);
            free(manifest);
            if (!virtual_romfs) { LOG("[fs] cannot mount virtual RomFS: %s\n", why); goto failed; }
            romfs_size = romfs_virtual_size(virtual_romfs);
            LOG("[fs] direct SAF RomFS mounted: %llu virtual bytes; no image generated\n", (unsigned long long)romfs_size);
        } else
#endif
        {
            snprintf(path, sizeof path, "%s.bin", g_romfs_dir);
            romfs_fd = open(path, O_RDONLY);
#ifdef __ANDROID__
            if (romfs_fd < 0) {
                extern int lasrecomp_external_open(const char *relative_path);
                romfs_fd = lasrecomp_external_open("romfs.bin");
            }
#endif
            struct stat sb;
            if (romfs_fd < 0 || lseek(romfs_fd, 0, SEEK_CUR) < 0 || fstat(romfs_fd, &sb) < 0 || sb.st_size < 0x50) {
                LOG("[fs] cannot open seekable RomFS image: %s\n", strerror(errno));
                goto failed;
            }
            romfs_size = (uint64_t)sb.st_size;
        }
        if (!rom_index(romfs_fd)) goto failed;
        romfs_mounted = true;
    }
    Storage *st = calloc(1, sizeof *st);
    if (!st) goto failed;
    st->fd = romfs_fd;
    st->size = romfs_size;
    pthread_mutex_unlock(&romfs_mount_lock);
    return service_new("IStorage(romfs)", storage, st);
failed:
    fs_reset();
    pthread_mutex_unlock(&romfs_mount_lock);
    return NULL;
}

// ------------------------------------------------------------------ host-directory filesystem
typedef struct { char root[1024]; } HostFs;
typedef struct { int fd; char path[1100]; } HostFile;
typedef struct { DIR *d; char path[1024]; int mode; } HostDir;

static const char *in_path(IpcReq *req, int i) {
    if (i < req->nx) return (const char *)(uintptr_t)req->x[i].addr;
    if (i < req->na) return (const char *)(uintptr_t)req->a[i].addr;
    return "";
}

static void host_path(HostFs *fs, const char *p, char *out, size_t n) {
    snprintf(out, n, "%s%s%s", fs->root, p[0] == '/' ? "" : "/", p);
}

static uint32_t errno_result(void) {
    if (errno == ENOENT || errno == ENOTDIR) return FS_PATH_NOT_FOUND;
    if (errno == EEXIST) return FS_PATH_EXISTS;
    if (errno == ENOTEMPTY) return FS_NOT_EMPTY;
    return MAKE_RESULT(2, 4000);
}

static void file(Service *s, IpcReq *req, IpcResp *resp) {
    HostFile *f = s->state;
    switch (req->cmd) {
    case 0: {  // Read(option, offset, size) -> B
        int64_t off = IN(int64_t, 8), size = IN(int64_t, 16);
        IpcBuf *b = out_buf(req, 0);
        if ((uint64_t)size > b->size) size = (int64_t)b->size;
        ssize_t n = pread(f->fd, (void *)(uintptr_t)b->addr, (size_t)size, off);
        if (strstr(f->path, "savedata")) {
            LOG("[save] read %s off %lld size %lld -> guest %llx\n", f->path, (long long)off, (long long)size, (unsigned long long)b->addr);
            extern void save_editor_file_read(const char *path, uint64_t addr, int64_t off, int64_t size);
            save_editor_file_read(f->path, b->addr, off, n);
            extern void flags_ext_save_read(const char *path, uint64_t addr, int64_t off, int64_t size);
            flags_ext_save_read(f->path, b->addr, off, n);
        }
        OUT(int64_t, 0) = n < 0 ? 0 : n;
        resp_size(resp, 8);
        break;
    }
    case 1: {  // Write(option, offset, size) <- A
        int64_t off = IN(int64_t, 8), size = IN(int64_t, 16);
        IpcBuf *a = in_buf(req, 0);
        if (strstr(f->path, "savedata"))
            LOG("[save] write %s off %lld size %lld <- guest %llx\n", f->path, (long long)off, (long long)size, (unsigned long long)a->addr);
        if (pwrite(f->fd, (void *)(uintptr_t)a->addr, (size_t)size, off) < 0) resp->result = errno_result();
        else if (strstr(f->path, "savedata")) {
            extern void flags_ext_save_written(const char *path, uint64_t addr, int64_t off, int64_t size);
            flags_ext_save_written(f->path, a->addr, off, size);
        }
        break;
    }
    case 2: fsync(f->fd); break;
    case 3: if (ftruncate(f->fd, IN(int64_t, 0))) resp->result = errno_result(); break;
    case 4: {
        struct stat sb;
        fstat(f->fd, &sb);
        OUT(int64_t, 0) = sb.st_size;
        resp_size(resp, 8);
        break;
    }
    default: LOG("[fs] IFile cmd %u (ok)\n", req->cmd);
    }
}

static void directory(Service *s, IpcReq *req, IpcResp *resp) {
    HostDir *d = s->state;
    switch (req->cmd) {
    case 0: {  // Read -> B buffer of 0x310-byte entries
        IpcBuf *b = out_buf(req, 0);
        uint8_t *out = (uint8_t *)(uintptr_t)b->addr;
        int64_t max = (int64_t)(b->size / 0x310), n = 0;
        struct dirent *e;
        while (n < max && (e = readdir(d->d))) {
            if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
#ifdef _WIN32  // no d_type
            char full[2048];
            struct stat es;
            snprintf(full, sizeof full, "%s/%s", d->path, e->d_name);
            bool isdir = !stat(full, &es) && S_ISDIR(es.st_mode);
#else
            bool isdir = e->d_type == DT_DIR;
#endif
            if ((isdir && !(d->mode & 1)) || (!isdir && !(d->mode & 2))) continue;
            uint8_t *ent = out + n * 0x310;
            memset(ent, 0, 0x310);
            strncpy((char *)ent, e->d_name, 0x300);
            ent[0x304] = isdir ? 0 : 1;
            if (!isdir) {
                char p[2048];
                struct stat sb;
                snprintf(p, sizeof p, "%s/%s", d->path, e->d_name);
                if (!stat(p, &sb)) *(int64_t *)(ent + 0x308) = sb.st_size;
            }
            n++;
        }
        OUT(int64_t, 0) = n;
        resp_size(resp, 8);
        break;
    }
    case 1: {  // GetEntryCount
        long pos = telldir(d->d);
        rewinddir(d->d);
        int64_t n = 0;
        struct dirent *e;
        while ((e = readdir(d->d)))
            if (strcmp(e->d_name, ".") && strcmp(e->d_name, "..")) n++;
        seekdir(d->d, pos);
        OUT(int64_t, 0) = n;
        resp_size(resp, 8);
        break;
    }
    }
}

static int rm_rf(const char *p, bool keep_root) {
    DIR *d = opendir(p);
    if (!d) return unlink(p);
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char c[2048];
        snprintf(c, sizeof c, "%s/%s", p, e->d_name);
        rm_rf(c, false);
    }
    closedir(d);
    return keep_root ? 0 : rmdir(p);
}

static void filesystem(Service *s, IpcReq *req, IpcResp *resp) {
    HostFs *fs = s->state;
    char p[2048], p2[2048];
    host_path(fs, in_path(req, 0), p, sizeof p);
    switch (req->cmd) {
    case 0: {  // CreateFile(option, size)
        int fd = open(p, O_CREAT | O_EXCL | O_RDWR, 0644);
        if (fd < 0) { resp->result = errno_result(); break; }
        if (ftruncate(fd, IN(int64_t, 8))) resp->result = errno_result();
        close(fd);
        break;
    }
    case 1: if (unlink(p)) resp->result = errno_result(); break;
    case 2: if (mkdir(p, 0755)) resp->result = errno_result(); break;
    case 3: if (rmdir(p)) resp->result = errno_result(); break;
    case 4: if (rm_rf(p, false)) resp->result = errno_result(); break;
    case 5: case 6:
        host_path(fs, in_path(req, 1), p2, sizeof p2);
        if (rename(p, p2)) resp->result = errno_result();
        break;
    case 7: {  // GetEntryType
        struct stat sb;
        if (stat(p, &sb)) { resp->result = FS_PATH_NOT_FOUND; break; }
        OUT(uint32_t, 0) = S_ISDIR(sb.st_mode) ? 0 : 1;
        resp_size(resp, 4);
        break;
    }
    case 8: {  // OpenFile(mode)
        uint32_t mode = IN(uint32_t, 0);
        int fd = open(p, (mode & 2) ? O_RDWR : O_RDONLY);
        if (fd < 0) { resp->result = errno_result(); break; }
        HostFile *f = calloc(1, sizeof *f);
        f->fd = fd;
        strlcpy(f->path, p, sizeof f->path);
        ipc_return_object(resp, service_new("IFile", file, f));
        break;
    }
    case 9: {  // OpenDirectory(mode)
        DIR *d = opendir(p);
        if (!d) { resp->result = errno_result(); break; }
        HostDir *hd = calloc(1, sizeof *hd);
        hd->d = d;
        hd->mode = (int)IN(uint32_t, 0);
        snprintf(hd->path, sizeof hd->path, "%s", p);
        ipc_return_object(resp, service_new("IDirectory", directory, hd));
        break;
    }
    case 10: break;  // Commit
    case 11: case 12: OUT(int64_t, 0) = 0x40000000; resp_size(resp, 8); break;
    case 13: rm_rf(p, true); break;
    case 14: memset(resp->data, 0, 0x20); resp_size(resp, 0x20); break;
    default: LOG("[fs] IFileSystem cmd %u (ok)\n", req->cmd);
    }
}

static Service *open_host_fs(const char *sub) {
    HostFs *fs = calloc(1, sizeof *fs);
    if (getenv("LARECOMP_SAVE_DIR")) g_save_dir = getenv("LARECOMP_SAVE_DIR");  // test runs use a scratch copy
    else if (rando_seed_dir()) {  // each randomizer seed has its own save slots
        static char seed_save[600];
        snprintf(seed_save, sizeof seed_save, "%s/save", rando_seed_dir());
        g_save_dir = seed_save;
    }
    snprintf(fs->root, sizeof fs->root, "%s/%s", g_save_dir, sub);
    char cmd[1200];
    snprintf(cmd, sizeof cmd, "%s", fs->root);
    for (char *q = cmd + 1; *q; q++)
        if (*q == '/') { *q = 0; mkdir(cmd, 0755); *q = '/'; }
    mkdir(cmd, 0755);
    LOG("[fs] mounted host directory %s\n", fs->root);
    return service_new("IFileSystem", filesystem, fs);
}

// ------------------------------------------------------------------ fsp-srv
SERVICE("fsp-srv", fsp_srv) {
    (void)s;
    switch (req->cmd) {
    case 1: break;  // SetCurrentProcess
    case 18: ipc_return_object(resp, open_host_fs("sdcard")); break;
    case 22: break;  // CreateSaveDataFileSystem
    case 51: case 53: {  // OpenSaveDataFileSystem(space, attribute)
        uint8_t type = IN(uint8_t, 0x8 + 0x18);  // attribute.type
        char sub[64];
        snprintf(sub, sizeof sub, "save_%u", type);
        ipc_return_object(resp, open_host_fs(sub));
        break;
    }
    case 200: { // OpenDataStorageByCurrentProcess
        Service *romfs = open_romfs_storage();
        if (romfs) ipc_return_object(resp, romfs);
        else resp->result = MAKE_RESULT(2, 4000);
        break;
    }
    case 202:  // OpenDataStorageByDataId (system data archives)
        LOG("[fs] OpenDataStorageByDataId %llx (not available)\n", IN(uint64_t, 8));
        resp->result = MAKE_RESULT(2, 1001);
        break;
    case 1005: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;  // GetGlobalAccessLogMode
    case 1003: case 1004: case 1006: break;
    case 1011: memset(resp->data, 0, 0x10); resp_size(resp, 0x10); break;
    default: LOG("[fs] fsp-srv cmd %u (ok)\n", req->cmd);
    }
}
