// Runs the production fsp-srv/IStorage handlers; only Android document access
// and unrelated host services are replaced. Synthetic files, no game required.
#define _GNU_SOURCE
#include "../runtime/hle.h" // host compatibility, before selecting the SAF path
#ifndef __ANDROID__
#define __ANDROID__ 1
#endif
#include "../runtime/services/fs.c"

const char *g_romfs_dir;
static Service *mounted;
static const char *manifest_text, *external_root, *seed_root;
static char local_romfs[4096];
static int manifest_error;

Service *service_new(const char *name, ServiceHandler handler, void *state) {
    Service *s = calloc(1, sizeof *s);
    s->name = name; s->handler = handler; s->state = state;
    return s;
}
void ipc_return_object(IpcResp *resp, Service *s) { resp->objects[resp->nobjects++] = s; }
const char *rando_seed_dir(void) { return seed_root; }
bool rando_romfs_override(const char *path, char *out, size_t cap) {
    struct stat sb;
    if (!seed_root) return false;
    snprintf(out, cap, "%s/romfs/%s", seed_root, path);
    return stat(out, &sb) == 0 && S_ISREG(sb.st_mode);
}
void romfs_file_read_hook(const char *path) { (void)path; }
void save_editor_file_read(const char *p, uint64_t a, int64_t o, int64_t n) { (void)p;(void)a;(void)o;(void)n; }
void flags_ext_save_read(const char *p, uint64_t a, int64_t o, int64_t n) { (void)p;(void)a;(void)o;(void)n; }
void flags_ext_save_written(const char *p, uint64_t a, int64_t o, int64_t n) { (void)p;(void)a;(void)o;(void)n; }
int lasrecomp_external_romfs_manifest(char **out, size_t *len) {
    if (manifest_error) { errno = manifest_error; return -1; }
    *out = strdup(manifest_text); *len = strlen(manifest_text);
    return 0;
}
int lasrecomp_external_open(const char *relative) {
    char path[8192];
    snprintf(path, sizeof path, "%s/%s", external_root, relative);
    return open(path, O_RDONLY);
}
void test_unmount(void) {
    if (mounted) { free(mounted->state); free(mounted); mounted = NULL; }
    fs_reset();
}
uint32_t test_mount(const char *local, const char *external, const char *manifest, const char *seed, int error) {
    test_unmount();
    snprintf(local_romfs, sizeof local_romfs, "%s/romfs", local);
    g_romfs_dir = local_romfs;
    external_root = external; manifest_text = manifest; seed_root = seed; manifest_error = error;
    IpcReq req = {.cmd = 200}; IpcResp resp = {0};
    fsp_srv(NULL, &req, &resp);
    if (resp.nobjects) mounted = resp.objects[0];
    return resp.result;
}
uint64_t test_storage_size(void) {
    IpcReq req = {.cmd = 4}; IpcResp resp = {0};
    mounted->handler(mounted, &req, &resp);
    uint64_t n; memcpy(&n, resp.data, 8); return n;
}
uint32_t test_storage_read(void *dst, uint64_t capacity, uint64_t off, uint64_t size) {
    uint64_t args[2] = {off, size};
    IpcReq req = {.cmd = 0, .data = (const uint8_t *)args, .data_size = sizeof args, .nb = 1};
    req.b[0] = (IpcBuf){(uint64_t)(uintptr_t)dst, capacity};
    IpcResp resp = {0};
    mounted->handler(mounted, &req, &resp);
    return resp.result;
}
