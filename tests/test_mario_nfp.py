"""Exercise real NFP handlers and object creation without NFC hardware."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NfpInterface(unittest.TestCase):
    def test_user_object_lifecycle_empty_devices_and_availability_event(self):
        code = r'''
#include <assert.h>
#include "services/nfp.c"
static unsigned event_creations;
Service *service_new(const char *name, ServiceHandler handler, void *state) {
    Service *s = calloc(1, sizeof *s);
    s->name = name; s->handler = handler; s->state = state;
    return s;
}
void ipc_return_object(IpcResp *r, Service *s) { r->objects[r->nobjects++] = s; }
KEvent *kernel_create_event_pair(uint32_t *w, uint32_t *r) {
    *w = 200; *r = 201; event_creations++; return NULL;
}
static IpcResp call(Service *s, uint32_t command) {
    IpcReq req = {.cmd = command}; IpcResp resp = {0};
    s->handler(s, &req, &resp); return resp;
}
int main(void) {
    IpcReq req = {0}; IpcResp response = {0};
    nfp_manager(NULL, &req, &response);
    assert(response.result == 0 && response.nobjects == 1 && response.objects[0]);
    Service *user = response.objects[0];
    response = call(user, 19); assert(response.data_size == 4 && response.data[0] == 0);
    response = call(user, 0); assert(response.result == 0);
    response = call(user, 19); assert(response.data_size == 4 && response.data[0] == 1);
    unsigned char devices[32]; memset(devices, 255, sizeof devices);
    req = (IpcReq){.cmd = 2, .nb = 1, .b = {{(uintptr_t)devices, sizeof devices}}};
    response = (IpcResp){0}; user->handler(user, &req, &response);
    assert(response.result == 0 && response.data_size == 4);
    uint32_t count; memcpy(&count, response.data, 4); assert(count == 0);
    for (unsigned i = 0; i < sizeof devices; i++) assert(devices[i] == 0);
    response = call(user, 23); assert(response.ncopy == 1 && response.copy_handles[0] == 201);
    response = call(user, 23); assert(response.ncopy == 1 && event_creations == 1);
    response = call(user, 5); assert(response.result != 0 && response.nobjects == 0);
    response = call(user, 1); assert(response.result == 0);
    response = call(user, 19); assert(response.data[0] == 0);
    user->on_close(user); free(user);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'mario_profile_config.h').write_text('/* handler test only */\n')
            source = folder / 'test.c'
            source.write_text(code)
            executable = folder / 'test'
            subprocess.run(['clang', '-std=gnu11', '-Wno-format', '-Werror=implicit-function-declaration',
                            '-DLASRECOMP_MARIO_TEST', '-I' + str(folder),
                            '-I' + str(ROOT / 'runtime'), str(source), '-o', str(executable)], check=True)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
