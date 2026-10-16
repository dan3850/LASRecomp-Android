#!/usr/bin/env python3
"""Exercise the Android runtime link flags with real profiler/mod exports.

Host dlopen does not reproduce Bionic's global-group policy. Inspect the ELF
DF_1_GLOBAL bit that Bionic uses, then test relocation and shared data on the
host with actual generated C and runtime/fnprof.c (no profiler substitutes).
"""
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
import unittest

from test_stable60_mod import CC, ROOT, fixture, mod


def flags_1(path):
    """Read DT_FLAGS_1 from ELF64 PT_DYNAMIC, independently of readelf text."""
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("expected little-endian ELF64")
    phoff, = struct.unpack_from("<Q", data, 32)
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    for index in range(phcount):
        header = phoff + index * phsize
        kind, = struct.unpack_from("<I", data, header)
        if kind == 2:  # PT_DYNAMIC
            offset, = struct.unpack_from("<Q", data, header + 8)
            size, = struct.unpack_from("<Q", data, header + 32)
            for at in range(offset, offset + size, 16):
                tag, value = struct.unpack_from("<QQ", data, at)
                if tag == 0:
                    break
                if tag == 0x6ffffffb:  # DT_FLAGS_1
                    return value
    return 0


class AndroidRuntimeLink(unittest.TestCase):
    def test_runtime_is_in_bionic_relocation_group_and_supplies_generated_code(self):
        scripts = ("compilar-lasrecomp-termux.sh", "tools/build-android-runtime.sh")
        for script in scripts:
            with self.subTest(script=script), tempfile.TemporaryDirectory(prefix="las-runtime-link-") as tmp:
                folder = Path(tmp)
                # Use the production runtime's actual linker options. All other
                # inputs are reduced to the two modules needed for this failure.
                text = (ROOT / script).read_text()
                command = next(command for command in text.replace("\\\n", " ").splitlines()
                               if "-shared" in command and "-Wl,--whole-archive" in command)
                options = [arg for arg in shlex.split(command) if arg.startswith("-Wl,")]
                platform = folder / "platform.c"
                platform.write_text("void plat_print_backtrace(void) {}\n")
                runtime = folder / "liblasrecomp_runtime.so"
                subprocess.run([*CC, "-std=gnu11", "-shared", "-fPIC", "-O2", *options,
                                str(ROOT / "runtime/fnprof.c"), str(ROOT / "runtime/mods.c"),
                                str(platform), "-o", str(runtime)], check=True)
                # RTLD_GLOBAL alone passes glibc tests but is insufficient for
                # Bionic relocation. This assertion fails on both old scripts.
                self.assertTrue(flags_1(runtime) & 2, script + " lacks DF_1_GLOBAL")

                nso = fixture(folder)
                changes, _ = mod.plan_sources(folder, nso, menu_compatible=True)
                source = folder / "game.c"
                generated = "\n".join(changes.values())
                generated = generated.replace(
                    "volatile int g_fnprof;\nvoid fnprof_hit(uint64_t a, uint64_t b, uint64_t c) {}\n", "")
                generated += ('\n__attribute__((visibility("default")))\n'
                              'volatile int *test_profiler_address(void) { return &g_fnprof; }\n')
                source.write_text(generated)
                game = folder / "liblasgame.so"
                subprocess.run([*CC, *mod.FLAGS, "-I" + str(ROOT / "runtime"), "-shared",
                                str(source), "-o", str(game)], check=True)
                # Separate process per runtime: no previous test can provide a
                # hidden substitute for one of the missing runtime symbols.
                probe = '''
import ctypes, os, sys
runtime, game, root = sys.argv[1:]
os.environ['LARECOMP_DATA_ROOT'] = root
os.environ.pop('LARECOMP_FNPROF', None)
os.environ.pop('LARECOMP_FNPROF_BT', None)
try:
    ctypes.CDLL(game, mode=os.RTLD_NOW)
except OSError as error:
    assert 'g_fnprof' in str(error) or 'fnprof_hit' in str(error) or 'rt_mod_nop' in str(error), error
else:
    raise AssertionError('unlinked consumer unexpectedly loaded without runtime')
engine = ctypes.CDLL(runtime, mode=os.RTLD_NOW | os.RTLD_GLOBAL)
for name in ('g_fnprof', 'fnprof_hit', 'rt_mod_nop'):
    getattr(engine, name)
consumer = ctypes.CDLL(game, mode=os.RTLD_NOW | os.RTLD_LOCAL)
profiler = ctypes.c_int.in_dll(engine, 'g_fnprof')
consumer.test_profiler_address.restype = ctypes.c_void_p
assert consumer.test_profiler_address() == ctypes.addressof(profiler)
result = (ctypes.c_uint64 * 6)()
consumer.test_run(result)
assert tuple(result) == (0, 30, 60, 7, 0x700101962c, 0xa0000000), tuple(result)
# Enable the real profiler: a generated call must resolve fnprof_hit as well.
profiler.value = 1
consumer.test_run(result)
assert profiler.value == 1
'''
                subprocess.run([sys.executable, "-c", probe, str(runtime), str(game), str(folder)], check=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
