"""Fatal diagnostics must survive invalid guest pointers and cyclic frames."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MarioAbortDiagnostics(unittest.TestCase):
    def test_result_frames_and_invalid_pointers(self):
        source = r'''
#include <stdio.h>
#include <sys/mman.h>
#include <string.h>
#define GUEST_LO 0x7000000000ull
#define GUEST_HI 0x7320000000ull
#define LOG(...) fprintf(stderr, __VA_ARGS__)
#ifdef BLOCK_OS_READERS
#include <fcntl.h>
#include <unistd.h>
#define open(...) (-1)
#define syscall(...) (-1L)
#endif
#include "mario_abort_diag.h"
int main(void) {
    void *memory = mmap((void *)GUEST_LO, 4096, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (memory == MAP_FAILED) return 2;
    uint32_t result = (123u << 9) | 153u;
    memcpy(memory, &result, 4);
    uint64_t *frame = (void *)(GUEST_LO + 512);
    frame[0] = GUEST_LO + 528; frame[1] = 0x7004144b78;
    frame[2] = GUEST_LO + 512; frame[3] = 0x7000123450;
    mario_abort_diag(GUEST_LO, 4, GUEST_LO, GUEST_LO + 512, GUEST_LO + 4096);
    munmap(memory, 4096);
    mario_abort_diag(GUEST_LO, 4, GUEST_LO, GUEST_LO + 512, 0);
    mario_abort_diag(0, 4, UINT64_MAX - 8, UINT64_MAX, 0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / 'test.c'
            path.write_text(source)
            executable = folder / 'test'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'runtime'), str(path), '-o', str(executable)], check=True)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('module=153 description=123', result.stderr)
            self.assertIn('lr=7000123450', result.stderr)
            self.assertEqual(result.stderr.count('[mario-abort] frame '), 2)
            self.assertEqual(result.stderr.count('info32='), 1)
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-Wno-unused-variable',
                            '-DBLOCK_OS_READERS', '-I' + str(ROOT / 'runtime'),
                            str(path), '-o', str(executable)], check=True)
            blocked = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
            self.assertEqual(blocked.returncode, 0, blocked.stderr)
            self.assertIn('module=153 description=123', blocked.stderr)
            self.assertEqual(blocked.stderr.count('[mario-abort] frame '), 2)
            self.assertEqual(blocked.stderr.count('info32='), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
