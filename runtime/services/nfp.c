// Minimal NFP user service: initialized interface, no NFC readers or tags.
// Protocol: switchbrew/libnx nx/source/services/nfc.c.
#include <stdlib.h>
#include <string.h>
#include "../hle.h"
#include "../ipc.h"

#ifdef LASRECOMP_MARIO_TEST
typedef struct {
    uint32_t initialized;
    uint32_t event_read;
} NfpUser;

static void nfp_close(Service *s) { free(s->state); }

static void nfp_user(Service *s, IpcReq *req, IpcResp *resp) {
    NfpUser *state = s->state;
    switch (req->cmd) {
    case 0:
        state->initialized = 1;
        LOG("[nfp] initialized; no NFC devices available\n");
        break;
    case 1: state->initialized = 0; break;
    case 2: {  // ListDevices: an empty list, no synthetic amiibo/device handles.
        IpcBuf *buffer = out_buf(req, 0);
        if (buffer && buffer->addr && buffer->size)
            memset((void *)(uintptr_t)buffer->addr, 0, buffer->size);
        OUT(uint32_t, 0) = 0;
        resp_size(resp, 4);
        break;
    }
    case 19:
        OUT(uint32_t, 0) = state->initialized;
        resp_size(resp, 4);
        break;
    case 23: {  // Availability-change event stays unsignaled: no devices change.
        if (!state->event_read) {
            uint32_t writable;
            kernel_create_event_pair(&writable, &state->event_read);
        }
        resp->copy_handles[resp->ncopy++] = state->event_read;
        break;
    }
    default:
        LOG("[nfp] unsupported device operation %u (no NFC devices)\n", req->cmd);
        resp->result = 0xF001;  // invalid operation; never report a tag operation as successful
        break;
    }
}

SERVICE("nfp:user", nfp_manager) {
    (void)s;
    if (req->cmd != 0) { resp->result = 0xF001; return; }
    NfpUser *state = calloc(1, sizeof *state);
    if (!state) { resp->result = 0xD001; return; }
    Service *user = service_new("NFP IUser", nfp_user, state);
    if (!user) { free(state); resp->result = 0xD001; return; }
    user->on_close = nfp_close;
    ipc_return_object(resp, user);
    LOG("[nfp] user interface created\n");
}
#endif
