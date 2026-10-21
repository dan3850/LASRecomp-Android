"""Compile only a tiny native harness around the production Mario spill-retention code.

No game library, APK, build cache or downloaded game data is touched.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" / "nvn" / "cmdbuf.c"


def retention_source():
    source = SOURCE.read_text()
    start = source.index("#define MARIO_SPILL_RETAIN_MAX_BYTES")
    end = source.index("\n#endif", start)
    return source[start:end]


HEADER = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#define FATAL(...) do { fprintf(stderr, __VA_ARGS__); exit(3); } while (0)
typedef struct { struct NvnSpillChunk *spill_chunks; } NvnCmdBuf;
'''

HARNESS = r'''
static NvnSpillChunk *new_chunk(unsigned char value) {
    NvnSpillChunk *chunk = malloc(sizeof(*chunk) + 65536);
    if (!chunk) exit(5);
    chunk->capacity = 65536;
    chunk->next = NULL;
    chunk->bytes[0] = value;
    return chunk;
}
int main(int argc, char **argv) {
    if (argc > 1 && argv[1][0] == 'c') {
        reserve_mario_spill(MARIO_SPILL_RETAIN_MAX_BYTES);
        reserve_mario_spill(1);
        return 6; // the cap guard should exit 3 first
    }
    NvnCmdBuf a = {0}, b = {0};
    NvnSpillChunk *first = new_chunk(0x42);
    NvnSpillChunk *second = new_chunk(0x43);
    NvnSpillChunk *third = new_chunk(0x44);
    a.spill_chunks = first;
    if (reserve_mario_spill(65536) != 65536) return 7;
    retain_finalized_spills(&a);
    if (a.spill_chunks != NULL || mario_retained_spills != first
            || first->bytes[0] != 0x42) return 8;
    second->next = third;
    b.spill_chunks = second;
    reserve_mario_spill(65536);
    reserve_mario_spill(65536);
    retain_finalized_spills(&b);
    if (b.spill_chunks != NULL || mario_retained_spills != second
            || second->next != third || third->next != first
            || mario_retained_count != 3
            || mario_spill_bytes != 196608
            || first->bytes[0] != 0x42) return 9;
    // The real Mario boot retains the chunks until process shutdown.
    // This isolated unit harness explicitly frees its fixture allocations.
    NvnSpillChunk *chunk = mario_retained_spills;
    while (chunk) {
        NvnSpillChunk *next = chunk->next;
        free(chunk);
        chunk = next;
    }
    return 0;
}
'''


class MarioSpillLifetimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("clang")
        if not cc:
            raise unittest.SkipTest("clang unavailable; needs native Termux toolchain")
        cls.temp = tempfile.TemporaryDirectory(prefix="mario-spill-test-")
        root = Path(cls.temp.name)
        cls.binary = root / "spill_test"
        source = root / "spill_test.c"
        source.write_text(HEADER + retention_source() + HARNESS)
        result = subprocess.run(
            [cc, "-std=gnu11", "-O0", "-pthread", str(source),
             "-o", str(cls.binary)],
            capture_output=True, text=True, check=False)
        if result.returncode:
            cls.temp.cleanup()
            raise AssertionError("standalone retention C compile failed:\n"
                                 + result.stderr)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def test_finalize_keeps_existing_command_bytes_and_chain(self):
        run = subprocess.run([str(self.binary)], capture_output=True,
                             text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_budget_enforced_before_allocation(self):
        run = subprocess.run([str(self.binary), "cap"],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 3, run.stderr)
        self.assertIn("spill retention cap reached", run.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
