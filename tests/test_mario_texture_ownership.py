"""Regression for Mario's corrupted NVN texture host pointer (Scudo SIGABRT)."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/nvn/objects.c"


class MarioTextureOwnership(unittest.TestCase):
    def test_finalizer_never_frees_guest_supplied_pointer(self):
        source = SOURCE.read_text()
        start = source.index("NVN(nvnTextureFinalize) {")
        end = source.index("\nNVN(nvnTextureSetDebugLabel)", start)
        finalizer = source[start:end]
        self.assertIn("mario_texture_owner_take(A(0))", finalizer)
        self.assertIn("SET_HOST(A(0), 0)", finalizer)
        self.assertIn("backend_texture_destroyed(t)", finalizer)
        self.assertIn("if (claimed != (uint64_t)(uintptr_t)t)", finalizer)
        self.assertIn("#else", finalizer)  # Zelda keeps its existing behavior.

    def test_real_registry_handles_corrupt_tag_duplicates_and_reinitialization(self):
        source = SOURCE.read_text()
        start = source.index("typedef struct MarioTextureOwner {")
        end = source.index("\n#endif\n\nstatic NvnTexture *texture_from_builder", start)
        registry = source[start:end]
        harness = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <pthread.h>
#include <assert.h>
typedef struct NvnTexture { uint64_t marker; } NvnTexture;
""" + registry + r"""
int main(void) {
    const uint64_t guest = 0x7000100080ULL;
    NvnTexture *one = calloc(1, sizeof *one), *two = calloc(1, sizeof *two);
    NvnTexture *old = NULL;
    assert(one && two);

    assert(mario_texture_owner_replace(guest, one, &old));
    assert(old == NULL);
    uint64_t original = (uint64_t)(uintptr_t)one;
    uint64_t damaged = (original & 0x00ffffffffffffffULL) | 0x0200000000000000ULL;
    if (damaged == original)
        damaged ^= 0x0100000000000000ULL;
    // The guest slot is corrupt, but the trusted allocation remains intact.
    assert(mario_texture_owner_take(guest) == one);
    assert(mario_texture_owner_take(guest) == NULL);
    free(one); // Free the known original allocation, never 'damaged'.

    assert(mario_texture_owner_replace(guest, two, &old));
    assert(old == NULL);
    NvnTexture *three = calloc(1, sizeof *three);
    assert(three);
    assert(mario_texture_owner_replace(guest, three, &old));
    assert(old == two);
    free(two);
    assert(mario_texture_owner_take(guest) == three);
    free(three);

    // Colliding buckets must still distinguish guest objects.
    NvnTexture *values[64];
    for (unsigned i = 0; i < 64; ++i) {
        values[i] = calloc(1, sizeof **values);
        assert(values[i]);
        assert(mario_texture_owner_replace(0x7000200000ULL + (uint64_t)i * 4096, values[i], &old));
        assert(old == NULL);
    }
    for (unsigned i = 0; i < 64; ++i) {
        assert(mario_texture_owner_take(0x7000200000ULL + (uint64_t)i * 4096) == values[i]);
        free(values[i]);
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="mario-texture-ownership-") as tmp:
            p = Path(tmp)
            src = p / "texture_owner.c"
            binary = p / "texture_owner"
            src.write_text(harness)
            build = subprocess.run([
                os.getenv("CC", "clang"), "-std=c11", "-O1", "-Wall", "-Wextra",
                "-Werror", "-pthread", str(src), "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
