"""Trace a wrapped resource registry without changing CPU or guest memory."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ResourceDiagnostics(unittest.TestCase):
    def test_wrapped_registry_and_observation_only(self):
        source = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <assert.h>
#define MAIN_BASE 0x7000000000ull
#define LOG(...) fprintf(stderr, __VA_ARGS__)
typedef struct { uint64_t x[32]; } Cpu;
static unsigned char memory[4096];
static bool mario_debug_read(uint64_t address, void *out, size_t size) {
    uintptr_t base = (uintptr_t)memory;
    if (address < base || address - base >= sizeof memory || size > sizeof memory - (address - base)) return false;
    memcpy(out, (void *)(uintptr_t)address, size); return true;
}
#include "mario_resource_diag.h"
static void put(size_t at, uint64_t value, size_t size) { memcpy(memory + at, &value, size); }
int main(void) {
    uintptr_t base = (uintptr_t)memory;
    put(0, base + 256, 8); put(8, 8, 4); put(12, 6, 4); put(16, 6, 4);
    put(128 + 8, base + 2048, 8); strcpy((char *)memory + 2048, "EffectData/AllPatchEffectData");
    for (unsigned i = 0; i < 6; i++) {
        put(256 + ((6 + i) % 8) * 8, base + 512 + i * 32, 8);
        put(512 + i * 32 + 8, base + 1024 + i * 32, 8);
        sprintf((char *)memory + 1024 + i * 32, "registry%u", i);
    }
    Cpu c = {0}; c.x[30] = MAIN_BASE + 0x8a1a5c;
    c.x[21] = base; c.x[20] = base + 128; c.x[23] = 5;
    Cpu original = c; unsigned char snapshot[sizeof memory]; memcpy(snapshot, memory, sizeof memory);
    mario_resource_trace(&c);
    assert(!memcmp(&original, &c, sizeof c)); assert(!memcmp(snapshot, memory, sizeof memory));
    c.x[21] = 0; mario_resource_trace(&c);
    c.x[30] = 0; mario_resource_trace(&c);
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
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('query=EffectData/AllPatchEffectData default=Scene count=6', result.stderr)
            for i in range(6):
                self.assertIn(f'name=registry{i}', result.stderr)
            self.assertEqual(result.stderr.count('[mario-resource] query='), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
