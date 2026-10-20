// Applet manager (appletOE), apm, and lm.
#include <stdlib.h>
#include <string.h>

#include "../hle.h"
#include "../ipc.h"
#include "../settings.h"

#define AM_NO_MESSAGE MAKE_RESULT(128, 3)
#define AM_NO_DATA MAKE_RESULT(128, 2)

static uint32_t msg_event_r, msg_event_w;
static KEvent *msg_event;
static uint32_t msg_queue[16];
static int msg_count;

static bool preselected_popped;
RT_ON_RESET(am_reset) {  // (reboot: the message queue starts over with FocusStateChanged)
    msg_event = NULL;
    msg_event_r = msg_event_w = 0;
    msg_count = 0;
    preselected_popped = false;
}

static void am_init_once(void) {
    if (msg_event) return;
    msg_event = kernel_create_event_pair(&msg_event_w, &msg_event_r);
    msg_queue[msg_count++] = 15;  // FocusStateChanged
    pthread_mutex_lock(&g_klock);
    kernel_signal(msg_event);
    pthread_mutex_unlock(&g_klock);
}

static uint32_t new_event(void) {
    uint32_t w, r;
    kernel_create_event_pair(&w, &r);
    return r;
}

#define UNHANDLED(iface) LOG("[am] %s cmd %u (unhandled, ok)\n", iface, req->cmd)

static void common_state_getter(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: resp->copy_handles[resp->ncopy++] = msg_event_r; break;  // GetEventHandle
    case 1:  // ReceiveMessage
        pthread_mutex_lock(&g_klock);
        if (msg_count) {
            OUT(uint32_t, 0) = msg_queue[0];
            memmove(msg_queue, msg_queue + 1, --msg_count * sizeof(uint32_t));
            if (!msg_count) msg_event->signaled = false;
            resp_size(resp, 4);
        } else {
            resp->result = AM_NO_MESSAGE;
        }
        pthread_mutex_unlock(&g_klock);
        break;
    case 5: OUT(uint8_t, 0) = 1; resp_size(resp, 1); break;   // GetOperationMode: docked
    case 6: OUT(uint32_t, 0) = 1; resp_size(resp, 4); break;  // GetPerformanceMode: boost
    case 8: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;   // GetBootMode
    case 9: OUT(uint8_t, 0) = 1; resp_size(resp, 1); break;   // GetCurrentFocusState: in focus
    case 13: case 61: resp->copy_handles[resp->ncopy++] = new_event(); break;
    case 60: {  // GetDefaultDisplayResolution
        int w = getenv("LARECOMP_DISPLAY_W") ? atoi(getenv("LARECOMP_DISPLAY_W")) : 1920;
        LOG("[am] GetDefaultDisplayResolution -> %dx1080\n", w);
        OUT(int32_t, 0) = w; OUT(int32_t, 4) = 1080; resp_size(resp, 8); break;
    }
    default: UNHANDLED("ICommonStateGetter");
    }
}

static void self_controller(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: LOG("[am] application requested exit\n"); exit(0);
    case 9: {  // GetLibraryAppletLaunchableEvent: an applet may be launched while idle.
#ifdef LASRECOMP_MARIO_TEST
        // A newly created, never-signaled event blocks Mario's main thread forever.
        // Signal through the kernel, not by writing 'signaled': preserve waiters and
        // the event-origin counters. Other application events remain unsignaled.
        uint32_t writable, readable;
        KEvent *launchable = kernel_create_event_pair(&writable, &readable);
        pthread_mutex_lock(&g_klock);
        kernel_signal(launchable);
        pthread_mutex_unlock(&g_klock);
        resp->copy_handles[resp->ncopy++] = readable;
#else
        resp->copy_handles[resp->ncopy++] = new_event();
#endif
        break;
    }
    case 40: OUT(uint64_t, 0) = 1; resp_size(resp, 8); break;  // CreateManagedDisplayLayer
    case 69: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;
    default: UNHANDLED("ISelfController");
    }
}

static void window_controller(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 1: OUT(uint64_t, 0) = 0x1234; resp_size(resp, 8); break;  // GetAppletResourceUserId
    default: UNHANDLED("IWindowController");
    }
}

static void generic_ok(Service *s, IpcReq *req, IpcResp *resp) {
    LOG("[am] %s cmd %u (ok)\n", s->name, req->cmd);
    resp_size(resp, 0x10);
}

// ------------------------------------------------------------------ IStorage / IStorageAccessor
typedef struct { uint8_t *data; uint64_t size; } AmStorage;

static void storage_accessor(Service *s, IpcReq *req, IpcResp *resp) {
    AmStorage *st = s->state;
    switch (req->cmd) {
    case 0: OUT(int64_t, 0) = (int64_t)st->size; resp_size(resp, 8); break;  // GetSize
    case 10: {  // Write(offset, A)
        int64_t off = IN(int64_t, 0);
        IpcBuf *a = in_buf(req, 0);
        uint64_t n = a->size;
        if ((uint64_t)off + n > st->size) n = st->size - (uint64_t)off;
        memcpy(st->data + off, (void *)(uintptr_t)a->addr, n);
        break;
    }
    case 11: {  // Read(offset, B)
        int64_t off = IN(int64_t, 0);
        IpcBuf *b = out_buf(req, 0);
        uint64_t n = b->size;
        if ((uint64_t)off + n > st->size) n = st->size - (uint64_t)off;
        memcpy((void *)(uintptr_t)b->addr, st->data + off, n);
        break;
    }
    default: LOG("[am] IStorageAccessor cmd %u (ok)\n", req->cmd);
    }
}

static void am_storage(Service *s, IpcReq *req, IpcResp *resp) {
    if (req->cmd == 0) ipc_return_object(resp, service_new("IStorageAccessor", storage_accessor, s->state));
    else LOG("[am] IStorage cmd %u (ok)\n", req->cmd);
}

static Service *new_am_storage(const void *data, uint64_t size) {
    AmStorage *st = calloc(1, sizeof *st);
    st->data = calloc(1, size);
    st->size = size;
    if (data) memcpy(st->data, data, size);
    return service_new("IStorage", am_storage, st);
}

#ifdef LASRECOMP_MARIO_TEST
// Command 0 must return an ILibraryAppletAccessor. An empty success response
// makes the SDK dereference a null interface (Mario boot: f_70040398a0).
typedef struct {
    uint8_t *data;
    uint64_t size;
} MarioAppletInput;

typedef struct {
    uint32_t applet_id, mode;
    MarioAppletInput input[3];
    unsigned input_count;
    uint32_t state_event_read;
    KEvent *state_event;
    bool started, completed, output_pending;
    uint8_t output[12];
} MarioLibraryApplet;

#define MARIO_APPLET_UNSUPPORTED 0xF201u

static void mario_library_applet_release(Service *s) {
    MarioLibraryApplet *a = s->state;
    if (a) {
        for (unsigned i = 0; i < a->input_count; i++) free(a->input[i].data);
        free(a);
    }
    s->state = NULL;
}

static void mario_library_applet_accessor(Service *s, IpcReq *req, IpcResp *resp) {
    MarioLibraryApplet *a = s->state;
    LOG("[mario-applet] accessor id=%u mode=%u cmd=%u started=%d completed=%d inputs=%u\n",
        a->applet_id, a->mode, req->cmd, (int)a->started, (int)a->completed, a->input_count);
    switch (req->cmd) {
    case 0: // GetAppletStateChangedEvent: only signaled once the applet completes.
        resp->copy_handles[resp->ncopy++] = a->state_event_read;
        return;
    case 1: // IsCompleted
        OUT(uint8_t, 0) = a->completed ? 1 : 0;
        resp_size(resp, 1);
        return;
    case 100: { // PushInData(IStorage)
        if (a->started || a->input_count >= 3 || req->ninput_services != 1 ||
            !req->input_services[0] ||
            strcmp(req->input_services[0]->name, "IStorage") != 0 ||
            !req->input_services[0]->state) break;
        const AmStorage *storage = req->input_services[0]->state;
        if (storage->size > 65536 || (storage->size && !storage->data)) break;
        uint8_t *copy = malloc(storage->size ? (size_t)storage->size : 1);
        if (!copy) break;
        if (storage->size) memcpy(copy, storage->data, (size_t)storage->size);
        MarioAppletInput *in = &a->input[a->input_count++];
        in->data = copy;
        in->size = storage->size;
        LOG("[mario-applet] PushInData index=%u size=%llu\n", a->input_count - 1,
            (unsigned long long)storage->size);
        return;
    }
    case 10: { // Start: locally accept a compatible single-player controller setup.
        if (a->started || a->applet_id != 0x0c || a->input_count != 3 ||
            a->input[1].size < 0x14 || a->input[2].size < 2) break;
        uint8_t support_mode = a->input[1].data[0x0a];
        int8_t min_players = (int8_t)a->input[2].data[0];
        int8_t max_players = (int8_t)a->input[2].data[1];
        LOG("[mario-applet] ControllerSupport mode=%u min=%d max=%d\n",
            support_mode, min_players, max_players);
        // No external controller picker is emulated. Never claim success when
        // the game requires multiple players or an unsupported applet mode.
        if (support_mode > 1 || min_players > 1 || max_players < 1) break;
        a->started = a->completed = a->output_pending = true;
        // ControllerSupportResultInfo: playerCount=1, selected NpadId=No1 (0),
        // followed by ControllerSupportResult=success (0), total 0xC bytes.
        a->output[0] = 1;
        pthread_mutex_lock(&g_klock);
        kernel_signal(a->state_event);
        pthread_mutex_unlock(&g_klock);
        LOG("[mario-applet] ControllerSupport completed: player=1 npad=0\n");
        return;
    }
    case 101: // PopOutData: a real 12-byte IStorage with the controller result.
        if (!a->completed || !a->output_pending) break;
        ipc_return_object(resp, new_am_storage(a->output, sizeof a->output));
        a->output_pending = false;
        return;
    case 30: // GetResult: success only when the controller setup finished.
        if (a->completed) return;
        break;
    case 120: // GetLibraryAppletInfo (AppletId, LibAppletMode).
        OUT(uint32_t, 0) = a->applet_id;
        OUT(uint32_t, 4) = a->mode;
        resp_size(resp, 8);
        return;
    case 20: case 25: // RequestExit / Terminate.
        if (a->started && !a->completed) {
            a->completed = true;
            pthread_mutex_lock(&g_klock);
            kernel_signal(a->state_event);
            pthread_mutex_unlock(&g_klock);
        }
        return;
    default: break;
    }
    LOG("[mario-applet] accessor id=%u cmd=%u unsupported state\n", a->applet_id, req->cmd);
    resp->result = MARIO_APPLET_UNSUPPORTED;
}

static void mario_library_applet_creator(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: {  // CreateLibraryApplet(id: u32, mode: u32) -> ILibraryAppletAccessor
        if (req->data_size < 8) { resp->result = MARIO_APPLET_UNSUPPORTED; break; }
        uint32_t id, mode;
        memcpy(&id, req->data, sizeof id);
        memcpy(&mode, req->data + 4, sizeof mode);
        LOG("[mario-applet] CreateLibraryApplet id=%u (0x%x) mode=%u\n", id, id, mode);
        MarioLibraryApplet *a = calloc(1, sizeof *a);
        if (!a) { resp->result = MARIO_APPLET_UNSUPPORTED; break; }
        a->applet_id = id;
        a->mode = mode;
        // The controller applet is locally handled without launching another game.
        if (id != 0x0c) {
            LOG("[mario-applet] unsupported applet id=%u\n", id);
            free(a);
            resp->result = MARIO_APPLET_UNSUPPORTED;
            break;
        }
        uint32_t event_w;
        a->state_event = kernel_create_event_pair(&event_w, &a->state_event_read);
        Service *accessor = service_new("ILibraryAppletAccessor", mario_library_applet_accessor, a);
        if (!accessor) { free(a); resp->result = MARIO_APPLET_UNSUPPORTED; break; }
        accessor->on_close = mario_library_applet_release;
        ipc_return_object(resp, accessor);
        break;
    }
    case 10: {  // CreateStorage(size: s64) -> IStorage
        if (req->data_size < 8) { resp->result = MARIO_APPLET_UNSUPPORTED; break; }
        int64_t size;
        memcpy(&size, req->data, sizeof size);
        LOG("[mario-applet] CreateStorage size=%lld\n", (long long)size);
        if (size < 0 || size > 32 * 1024 * 1024) {
            resp->result = MARIO_APPLET_UNSUPPORTED;
            break;
        }
        ipc_return_object(resp, new_am_storage(NULL, (uint64_t)size));
        break;
    }
    default:
        LOG("[mario-applet] creator cmd=%u unsupported\n", req->cmd);
        resp->result = MARIO_APPLET_UNSUPPORTED;
        break;
    }
}
#endif

extern const uint8_t g_user_id[16];

static void application_functions(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 1:  // PopLaunchParameter(kind)
        if (IN(uint32_t, 0) == 2 && !preselected_popped) {  // PreselectedUser
            uint8_t p[0x88] = {0};
            *(uint32_t *)p = 0xC79497CA;
            *(uint32_t *)(p + 4) = 1;
            memcpy(p + 8, g_user_id, 16);
            preselected_popped = true;
            ipc_return_object(resp, new_am_storage(p, sizeof p));
        } else {
            resp->result = AM_NO_DATA;
        }
        break;
    case 20: OUT(uint64_t, 0) = 0; resp_size(resp, 8); break;  // EnsureSaveData
    case 21: {  // GetDesiredLanguage: the game's text language (settings: runtime/settings.c, "language")
        char lang[8] = {0};
        snprintf(lang, sizeof lang, "%s", settings_language());
        memcpy(resp->data, lang, 8);
        resp_size(resp, 8);
        break;
    }
    case 23: memcpy(resp->data, "1.0.0", 6); resp_size(resp, 0x10); break;
    case 40: OUT(uint8_t, 0) = 0; resp_size(resp, 1); break;  // NotifyRunning
    case 130: case 140: resp->copy_handles[resp->ncopy++] = new_event(); break;
    default: UNHANDLED("IApplicationFunctions");
    }
}

static void application_proxy(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    static const struct { int cmd; const char *name; ServiceHandler h; } subs[] = {
        {0, "ICommonStateGetter", common_state_getter},
        {1, "ISelfController", self_controller},
        {2, "IWindowController", window_controller},
        {3, "IAudioController", generic_ok},
        {4, "IDisplayController", generic_ok},
        {10, "IProcessWindingController", generic_ok},
        #ifdef LASRECOMP_MARIO_TEST
        {11, "ILibraryAppletCreator", mario_library_applet_creator},
#else
        {11, "ILibraryAppletCreator", generic_ok},
#endif
        {20, "IApplicationFunctions", application_functions},
        {1000, "IDebugFunctions", generic_ok},
    };
    for (unsigned i = 0; i < sizeof subs / sizeof *subs; i++) {
        if (subs[i].cmd == (int)req->cmd) {
            ipc_return_object(resp, service_new(subs[i].name, subs[i].h, NULL));
            return;
        }
    }
    UNHANDLED("IApplicationProxy");
}

SERVICE("appletOE", applet_oe) {
    (void)s;
    am_init_once();
    if (req->cmd == 0) ipc_return_object(resp, service_new("IApplicationProxy", application_proxy, NULL));
    else UNHANDLED("appletOE");
}

// ------------------------------------------------------------------ apm
static void apm_session(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    if (req->cmd == 1) { OUT(uint32_t, 0) = 0x92220008; resp_size(resp, 4); }  // GetPerformanceConfiguration
}

SERVICE("apm", apm) {
    (void)s;
    if (req->cmd == 0) ipc_return_object(resp, service_new("apm:ISession", apm_session, NULL));
    else if (req->cmd == 1) { OUT(uint32_t, 0) = 1; resp_size(resp, 4); }
}

// ------------------------------------------------------------------ lm (guest log output)
static void lm_logger(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s; (void)resp;
    if (req->cmd != 0) return;
    IpcBuf *b = in_buf(req, 0);
    if (!b || !b->size) return;
    // Log packets are TLV chunks after a 0x18-byte header; print the string chunks.
    const uint8_t *p = (const uint8_t *)(uintptr_t)b->addr, *end = p + b->size;
    p += 0x18;
    char line[1024];
    int n = 0;
    while (p + 2 <= end) {
        uint8_t key = p[0], len = p[1];
        p += 2;
        if (p + len > end) break;
        if (key == 2 || key == 4 || key == 5 || key == 6 || key == 7) {  // message, file, function, module, thread
            n += snprintf(line + n, sizeof line - n, "%s%.*s", n ? " | " : "", len, (const char *)p);
            if (n >= (int)sizeof line) break;
        }
        p += len;
    }
    if (n) LOG("[lm] %s\n", line);
}

SERVICE("lm", lm) {
    (void)s;
    if (req->cmd == 0) ipc_return_object(resp, service_new("lm:ILogger", lm_logger, NULL));
}
