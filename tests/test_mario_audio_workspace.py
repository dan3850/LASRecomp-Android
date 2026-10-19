"""Compile the production audio workspace IPC case for both game profiles."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AudioWorkspace(unittest.TestCase):
    def test_workspace_response_and_profile_isolation(self):
        text = (ROOT / 'runtime/services/audio.c').read_text()
        start = text.index('    case 1: {  // GetWorkBufferSize', text.index('SERVICE("audren:u"'))
        end = text.index('    case 2:', start)
        case = text[start:end]
        code = '''
#include <stdint.h>
#include <stdio.h>
#define LOG(...) fprintf(stderr, __VA_ARGS__)
typedef struct { uint64_t data; int bytes; } Response;
#define OUT(type, offset) (*(type *)((char *)&resp->data + offset))
static void resp_size(Response *r, int bytes) { r->bytes = bytes; }
int main(void) {
    Response response = {0}; Response *resp = &response;
    switch (1) {
''' + case + '''
    }
#ifdef LASRECOMP_MARIO_TEST
    if (response.data != 4096) return 1;
#else
    if (response.data != 16777216) return 2;
#endif
    if (response.bytes != 8 || (response.data & 4095)) return 3;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / 'test.c'
            source.write_text(code)
            for mario in (False, True):
                executable = folder / ('mario' if mario else 'zelda')
                subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                                *(['-DLASRECOMP_MARIO_TEST'] if mario else []),
                                str(source), '-o', str(executable)], check=True)
                result = subprocess.run([str(executable)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
