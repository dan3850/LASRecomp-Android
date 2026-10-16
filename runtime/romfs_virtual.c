// Same on-disk format/layout as romfs_build.c; payload extents stay external.
#include "romfs_virtual.h"
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define EMPTY UINT32_MAX
#define DATA_START 0x200u
#define FD_CACHE_SIZE 32
#define INDEX_LIMIT (64u << 20)

typedef struct {
    char *path;
    const char *name;
    uint64_t size, data;
    uint32_t meta, parent, first_dir, first_file, next;
    bool directory;
} Node;
typedef struct { int fd; uint32_t node; uint64_t used; } CachedFd;
struct RomfsVirtual {
    Node *nodes;
    uint32_t count, ndirs, nfiles;
    uint32_t *dirs, *files;
    uint8_t header[DATA_START], *tables;
    uint64_t tables_at, tables_size, size, clock;
    CachedFd cache[FD_CACHE_SIZE];
    RomfsOpenFile open_file;
    void *context;
    pthread_mutex_t lock;
};

static uint32_t align4(uint32_t n) { return (n + 3) & ~3u; }
static uint64_t align16(uint64_t n) { return (n + 15) & ~15ull; }
static void put32(uint8_t *p, uint32_t n) {
    for (int i = 0; i < 4; i++) p[i] = (uint8_t)(n >> (8 * i));
}
static void put64(uint8_t *p, uint64_t n) {
    for (int i = 0; i < 8; i++) p[i] = (uint8_t)(n >> (8 * i));
}
static uint32_t name_hash(uint32_t parent, const char *name) {
    uint32_t h = parent ^ 123456789u;
    for (const unsigned char *p = (const unsigned char *)name; *p; p++)
        h = ((h >> 5) | (h << 27)) ^ *p;
    return h;
}
static uint32_t bucket_count(uint32_t n) {
    if (n < 3) return 3;
    if (n < 19) return n | 1;
    while (!(n % 2) || !(n % 3) || !(n % 5) || !(n % 7) ||
           !(n % 11) || !(n % 13) || !(n % 17)) n++;
    return n;
}
static int node_cmp(const void *a, const void *b) {
    return strcmp(((const Node *)a)->path, ((const Node *)b)->path);
}
static uint32_t find_node(RomfsVirtual *r, const char *path) {
    Node key = {.path = (char *)path};
    Node *n = bsearch(&key, r->nodes, r->count, sizeof *r->nodes, node_cmp);
    return n ? (uint32_t)(n - r->nodes) : EMPTY;
}
static bool valid_path(const char *path) {
    if (!*path || strlen(path) > 4095) return false;
    unsigned depth = 0;
    for (const char *p = path; *p;) {
        const char *end = strchr(p, '/');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        if (!len || len > 255 || (len == 1 && *p == '.') ||
            (len == 2 && p[0] == '.' && p[1] == '.') || ++depth > 49) return false;
        for (size_t i = 0; i < len; i++)
            if (p[i] == '\\' || p[i] == '\t' || p[i] == '\r' || p[i] == '\n') return false;
        if (!end) break;
        p = end + 1;
        if (!*p) return false;
    }
    return true;
}
static void flatten(RomfsVirtual *r, uint32_t dir) {
    for (uint32_t i = r->nodes[dir].first_file; i != EMPTY; i = r->nodes[i].next)
        r->files[r->nfiles++] = i;
    for (uint32_t i = r->nodes[dir].first_dir; i != EMPTY; i = r->nodes[i].next)
        r->dirs[r->ndirs++] = i;
    for (uint32_t i = r->nodes[dir].first_dir; i != EMPTY; i = r->nodes[i].next)
        flatten(r, i);
}

void romfs_virtual_close(RomfsVirtual *r) {
    if (!r) return;
    for (unsigned i = 0; i < FD_CACHE_SIZE; i++) if (r->cache[i].fd >= 0) close(r->cache[i].fd);
    for (uint32_t i = 0; i < r->count; i++) free(r->nodes[i].path);
    free(r->nodes); free(r->dirs); free(r->files); free(r->tables);
    pthread_mutex_destroy(&r->lock);
    free(r);
}

RomfsVirtual *romfs_virtual_create(const char *manifest, size_t length,
                                  RomfsOpenFile open_file, void *context,
                                  char *why, size_t why_size) {
    #define FAIL(code, ...) do { error = code; if (why && why_size) snprintf(why, why_size, __VA_ARGS__); goto fail; } while (0)
    int error = EINVAL;
    RomfsVirtual *r = NULL;
    if (why && why_size) *why = 0;
    if (!manifest || !length || length > INDEX_LIMIT || !open_file || memchr(manifest, 0, length))
        FAIL(EINVAL, "Invalid or oversized RomFS index");
    r = calloc(1, sizeof *r);
    if (!r) FAIL(ENOMEM, "Out of memory for virtual RomFS");
    for (unsigned i = 0; i < FD_CACHE_SIZE; i++) r->cache[i].fd = -1;
    int err = pthread_mutex_init(&r->lock, NULL);
    if (err) { free(r); r = NULL; FAIL(err, "Cannot initialize RomFS lock"); }
    r->open_file = open_file; r->context = context;
    size_t capacity = 1;
    for (size_t i = 0; i < length; i++) if (manifest[i] == '\n') capacity++;
    if (capacity > UINT32_MAX || capacity > SIZE_MAX / sizeof *r->nodes)
        FAIL(EOVERFLOW, "Too many RomFS entries");
    r->nodes = calloc(capacity, sizeof *r->nodes);
    if (!r->nodes) FAIL(ENOMEM, "Out of memory for RomFS entries");
    r->nodes[r->count++] = (Node){.path = strdup(""), .directory = true};
    if (!r->nodes[0].path) FAIL(ENOMEM, "Out of memory for RomFS root");
    for (size_t pos = 0; pos < length;) {
        const char *line = manifest + pos, *end = memchr(line, '\n', length - pos);
        if (!end || end - line < 3 || line[1] != '\t' || (line[0] != 'D' && line[0] != 'F'))
            FAIL(EINVAL, "Malformed RomFS index record");
        bool directory = line[0] == 'D';
        const char *path = line + 2;
        uint64_t size = 0;
        if (!directory) {
            if (path == end || *path < '0' || *path > '9') FAIL(EINVAL, "Missing RomFS file size");
            while (path < end && *path >= '0' && *path <= '9') {
                unsigned digit = (unsigned)(*path++ - '0');
                if (size > ((uint64_t)INT64_MAX - digit) / 10) FAIL(EOVERFLOW, "RomFS file size overflow");
                size = size * 10 + digit;
            }
            if (path == end || *path++ != '\t') FAIL(EINVAL, "Malformed RomFS file size");
        }
        char *copy = strndup(path, (size_t)(end - path));
        if (!copy) FAIL(ENOMEM, "Out of memory for RomFS filename");
        r->nodes[r->count++] = (Node){.path = copy, .directory = directory, .size = size};
        if (!valid_path(copy)) FAIL(EINVAL, "Invalid RomFS path: %.160s", copy);
        pos = (size_t)(end - manifest) + 1;
    }
    qsort(r->nodes, r->count, sizeof *r->nodes, node_cmp);
    for (uint32_t i = 0; i < r->count; i++) {
        Node *n = r->nodes + i;
        if (i && !strcmp(n->path, r->nodes[i - 1].path)) FAIL(EINVAL, "Duplicate RomFS path: %.160s", n->path);
        n->first_dir = n->first_file = n->next = EMPTY;
        char *slash = strrchr(n->path, '/');
        n->name = slash ? slash + 1 : n->path;
        char parent[4096];
        if (slash) {
            size_t len = (size_t)(slash - n->path);
            memcpy(parent, n->path, len); parent[len] = 0;
        }
        n->parent = slash ? find_node(r, parent) : 0;
        if (n->parent == EMPTY || !r->nodes[n->parent].directory)
            FAIL(ENOENT, "RomFS parent directory missing: %.160s", n->path);
    }
    // Reverse sorted insertion gives name-sorted sibling chains.
    for (uint32_t i = r->count - 1; i > 0; i--) {
        Node *n = r->nodes + i, *p = r->nodes + n->parent;
        uint32_t *first = n->directory ? &p->first_dir : &p->first_file;
        n->next = *first; *first = i;
    }
    r->dirs = malloc(r->count * sizeof *r->dirs);
    r->files = malloc(r->count * sizeof *r->files);
    if (!r->dirs || !r->files) FAIL(ENOMEM, "Out of memory for RomFS layout");
    r->dirs[r->ndirs++] = 0;
    flatten(r, 0);
    if (!r->nfiles) FAIL(ENOENT, "No files in RomFS folder");
    uint64_t dsize = 0, fsize = 0, data = 0;
    for (uint32_t i = 0; i < r->ndirs; i++) {
        Node *n = r->nodes + r->dirs[i];
        n->meta = (uint32_t)dsize;
        dsize += 0x18 + align4((uint32_t)strlen(n->name));
        if (dsize >= EMPTY) FAIL(EOVERFLOW, "RomFS directory table overflow");
    }
    for (uint32_t i = 0; i < r->nfiles; i++) {
        Node *n = r->nodes + r->files[i];
        n->meta = (uint32_t)fsize;
        fsize += 0x20 + align4((uint32_t)strlen(n->name));
        n->data = DATA_START + align16(data);
        if (fsize >= EMPTY || n->data > (uint64_t)INT64_MAX - 16 ||
            n->size > (uint64_t)INT64_MAX - n->data - 16)
            FAIL(EOVERFLOW, "RomFS layout overflow");
        data = n->data - DATA_START + n->size;
    }
    uint32_t nbd = bucket_count(r->ndirs), nbf = bucket_count(r->nfiles);
    r->tables_at = (DATA_START + data + 3) & ~3ull;
    r->tables_size = 4ull * nbd + dsize + 4ull * nbf + fsize;
    if (r->tables_size > INDEX_LIMIT || r->tables_at > (uint64_t)INT64_MAX - r->tables_size)
        FAIL(EOVERFLOW, "RomFS metadata too large");
    r->size = r->tables_at + r->tables_size;
    r->tables = calloc(1, (size_t)r->tables_size);
    if (!r->tables) FAIL(ENOMEM, "Out of memory for RomFS tables");
    uint8_t *dh = r->tables, *dm = dh + 4ull * nbd;
    uint8_t *fh = dm + dsize, *fm = fh + 4ull * nbf;
    memset(dh, 0xff, 4ull * nbd); memset(fh, 0xff, 4ull * nbf);
    for (uint32_t i = 0; i < r->ndirs; i++) {
        Node *n = r->nodes + r->dirs[i];
        uint8_t *e = dm + n->meta;
        uint32_t parent = r->nodes[n->parent].meta;
        uint32_t bucket = name_hash(parent, n->name) % nbd;
        put32(e, parent);
        put32(e + 4, n->next == EMPTY ? EMPTY : r->nodes[n->next].meta);
        put32(e + 8, n->first_dir == EMPTY ? EMPTY : r->nodes[n->first_dir].meta);
        put32(e + 12, n->first_file == EMPTY ? EMPTY : r->nodes[n->first_file].meta);
        memcpy(e + 16, dh + 4ull * bucket, 4);
        put32(e + 20, (uint32_t)strlen(n->name));
        memcpy(e + 0x18, n->name, strlen(n->name));
        put32(dh + 4ull * bucket, n->meta);
    }
    for (uint32_t i = 0; i < r->nfiles; i++) {
        Node *n = r->nodes + r->files[i];
        uint8_t *e = fm + n->meta;
        uint32_t parent = r->nodes[n->parent].meta;
        uint32_t bucket = name_hash(parent, n->name) % nbf;
        put32(e, parent);
        put32(e + 4, n->next == EMPTY ? EMPTY : r->nodes[n->next].meta);
        put64(e + 8, n->data - DATA_START); put64(e + 16, n->size);
        memcpy(e + 24, fh + 4ull * bucket, 4);
        put32(e + 28, (uint32_t)strlen(n->name));
        memcpy(e + 0x20, n->name, strlen(n->name));
        put32(fh + 4ull * bucket, n->meta);
    }
    uint64_t h[10] = {0x50, r->tables_at, 4ull * nbd, r->tables_at + 4ull * nbd, dsize,
        r->tables_at + 4ull * nbd + dsize, 4ull * nbf, r->size - fsize, fsize, DATA_START};
    for (unsigned i = 0; i < 10; i++) put64(r->header + 8 * i, h[i]);
    return r;
fail:
    romfs_virtual_close(r);
    errno = error;
    return NULL;
    #undef FAIL
}

uint64_t romfs_virtual_size(const RomfsVirtual *r) { return r ? r->size : 0; }

static int file_fd(RomfsVirtual *r, uint32_t node) {
    unsigned slot = 0;
    for (unsigned i = 0; i < FD_CACHE_SIZE; i++) {
        if (r->cache[i].fd >= 0 && r->cache[i].node == node) {
            r->cache[i].used = ++r->clock;
            return r->cache[i].fd;
        }
        if (r->cache[i].used < r->cache[slot].used) slot = i;
    }
    int fd = r->open_file(r->context, r->nodes[node].path);
    if (fd < 0) return -1;
    struct stat sb;
    int error = 0;
    if (lseek(fd, 0, SEEK_CUR) < 0 || fstat(fd, &sb) < 0) error = errno;
    else if (S_ISREG(sb.st_mode) && (sb.st_size < 0 || (uint64_t)sb.st_size != r->nodes[node].size)) error = EIO;
    if (error) { close(fd); errno = error; return -1; }
    if (r->cache[slot].fd >= 0) close(r->cache[slot].fd);
    r->cache[slot] = (CachedFd){fd, node, ++r->clock};
    return fd;
}

ssize_t romfs_virtual_read(RomfsVirtual *r, void *buffer, size_t size, uint64_t off) {
    if (!r || (!buffer && size) || off > r->size || size > r->size - off) { errno = EINVAL; return -1; }
    if (size > (size_t)SSIZE_MAX) { errno = EOVERFLOW; return -1; }
    int err = pthread_mutex_lock(&r->lock);
    if (err) { errno = err; return -1; }
    uint8_t *dst = buffer;
    size_t done = 0;
    while (done < size) {
        uint64_t at = off + done, available;
        size_t n = size - done;
        const uint8_t *mem = NULL;
        uint32_t node = EMPTY;
        if (at < DATA_START) {
            mem = r->header + at; available = DATA_START - at;
        } else if (at >= r->tables_at) {
            mem = r->tables + (at - r->tables_at); available = r->size - at;
        } else {
            uint32_t lo = 0, hi = r->nfiles;
            while (lo < hi) {
                uint32_t mid = lo + (hi - lo) / 2;
                if (r->nodes[r->files[mid]].data <= at) lo = mid + 1; else hi = mid;
            }
            if (lo && at - r->nodes[r->files[lo - 1]].data < r->nodes[r->files[lo - 1]].size) {
                node = r->files[lo - 1];
                available = r->nodes[node].size - (at - r->nodes[node].data);
            } else available = (lo < r->nfiles ? r->nodes[r->files[lo]].data : r->tables_at) - at;
        }
        if (available < n) n = (size_t)available;
        if (mem) memcpy(dst + done, mem, n);
        else if (node == EMPTY) memset(dst + done, 0, n);
        else {
            int fd = file_fd(r, node);
            if (fd < 0) goto fail;
            size_t read_bytes = 0;
            while (read_bytes < n) {
                ssize_t got = pread(fd, dst + done + read_bytes, n - read_bytes,
                                    (off_t)(at - r->nodes[node].data + read_bytes));
                if (got < 0 && errno == EINTR) continue;
                if (got <= 0) { if (!got) errno = EIO; goto fail; }
                read_bytes += (size_t)got;
            }
        }
        done += n;
    }
    pthread_mutex_unlock(&r->lock);
    return (ssize_t)done;
fail: {
    int error = errno;
    fprintf(stderr, "[romfs] direct read failed at 0x%llx: %s\n", (unsigned long long)(off + done), strerror(error));
    pthread_mutex_unlock(&r->lock);
    errno = error;
    return -1;
}
}
