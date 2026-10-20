"""Regression: Mario copies NVN texture handles out of temporary guest structs."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/nvn/objects.c"


class MarioTextureOwnership(unittest.TestCase):
    def test_finalizer_uses_live_allocation_not_temporary_guest_address(self):
        source = SOURCE.read_text()
        init = source[source.index("NVN(nvnTextureInitialize) {"):
                      source.index("\nNVN(nvnTextureFinalize)", source.index("NVN(nvnTextureInitialize) {"))]
        finalizer = source[source.index("NVN(nvnTextureFinalize) {"):
                           source.index("\nNVN(nvnTextureSetDebugLabel)", source.index("NVN(nvnTextureFinalize) {"))]
        self.assertIn("mario_texture_owner_add(t)", init)
        self.assertNotIn("backend_texture_destroyed", init)
        self.assertNotIn("mario_texture_owner_replace", init)
        self.assertIn("mario_texture_owner_take(claimed)", finalizer)
        self.assertIn("SET_HOST(A(0), 0)", finalizer)
        self.assertIn("backend_texture_destroyed(t)", finalizer)
        self.assertIn("if (claimed != (uint64_t)(uintptr_t)t)", finalizer)
        self.assertIn("#else", finalizer)  # Zelda retains previous behavior.

    def test_real_registry_supports_copied_guest_handles_and_invalid_top_byte(self):
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
typedef struct { uint64_t host; } GuestTexture;
""" + registry + r"""
int main(void) {
    NvnTexture *one = calloc(1, sizeof *one);
    NvnTexture *two = calloc(1, sizeof *two);
    NvnTexture *three = calloc(1, sizeof *three);
    assert(one && two && three);
    GuestTexture temp = {(uint64_t)(uintptr_t)one};
    assert(mario_texture_owner_add(one));
    GuestTexture copied = temp; // Guest copies the NVNtexture into permanent memory.
    temp.host = (uint64_t)(uintptr_t)two; // Same temporary object reused.
    assert(mario_texture_owner_add(two));
    temp.host = (uint64_t)(uintptr_t)three;
    assert(mario_texture_owner_add(three));

    // Reinitializing the temporary must not destroy the copied allocation.
    uint64_t damaged = (copied.host & UINT64_C(0x00ffffffffffffff)) |
                        UINT64_C(0x0200000000000000);
    if (damaged == copied.host)
        damaged ^= UINT64_C(0x0100000000000000);
    assert(mario_texture_owner_take(damaged) == one);
    assert(mario_texture_owner_take(copied.host) == NULL);
    free(one);
    assert(mario_texture_owner_take((uint64_t)(uintptr_t)two) == two);
    free(two);
    assert(mario_texture_owner_take(temp.host) == three);
    free(three);
    assert(mario_texture_owner_take(temp.host) == NULL);

    // Independent registrations must be found even when the buckets collide.
    NvnTexture *values[64];
    for (unsigned i = 0; i < 64; ++i) {
        values[i] = calloc(1, sizeof **values);
        assert(values[i] && mario_texture_owner_add(values[i]));
    }
    for (unsigned i = 0; i < 64; ++i) {
        assert(mario_texture_owner_take((uint64_t)(uintptr_t)values[i]) == values[i]);
        free(values[i]);
    }
    assert(mario_texture_owner_take(UINT64_C(0x200007874686c70)) == NULL);
    assert(mario_texture_owner_take(0) == NULL);
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
