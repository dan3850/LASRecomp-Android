#!/usr/bin/env python3
"""Real Java import/state code and real C selection hook, without Android hardware."""
import ctypes
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
javac = os.environ.get("JAVAC", shutil.which("javac"))
java = os.environ.get("JAVA", shutil.which("java"))
if not javac or not java:
    raise SystemExit("Set JAVAC/JAVA to existing JDK executables")

with tempfile.TemporaryDirectory(prefix="las-mod-menu-") as temporary:
    folder = Path(temporary)
    subprocess.run([javac, "-source", "8", "-target", "8", "-d", str(folder),
        str(ROOT / "android/src/com/retroaura/lasrecomp/Stable60Patch.java"),
        str(ROOT / "tests/Stable60PatchTest.java")], check=True)
    subprocess.run([java, "-cp", str(folder), "com.retroaura.lasrecomp.Stable60PatchTest", str(folder)], check=True)

    harness = folder / "hook.c"
    harness.write_text('#include "' + str(ROOT / "runtime/mods.c") + '"\nvoid test_reset(void) { mods_reset(); }\n')
    library = folder / "hook.so"
    subprocess.run([*shlex.split(os.environ.get("CC", "clang")), "-std=gnu11", "-shared", "-fPIC", "-O1",
                    str(harness), "-o", str(library)], check=True)
    hook = ctypes.CDLL(str(library))
    hook.rt_mod_nop.argtypes = [ctypes.c_uint64]
    hook.rt_mod_nop.restype = ctypes.c_int
    os.environ["LARECOMP_DATA_ROOT"] = str(folder)
    marker = folder / "mods/stable60-v2.enabled"
    # Java ended with the marker disabled. C must observe the SAME persisted state.
    assert hook.rt_mod_nop(0x7001019608) == 0
    marker.write_text("AE16F71E002AF8CB059A9A74C4D90F34BA984892\n")
    assert hook.rt_mod_nop(0x7001019608) == 0  # selection takes effect on restart/reset
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 1
    assert hook.rt_mod_nop(0x7001019628) == 1
    assert hook.rt_mod_nop(0x700101962c) == 0
    marker.write_text("disabled\n")
    assert hook.rt_mod_nop(0x7001019628) == 1  # no file reads on the warm path
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 0
    marker.write_text("0000000000000000000000000000000000000000\n")
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 0
    marker.write_bytes(b"x" * 97)
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 0
    print("Native mod selection: both sites, disabled/default/invalid states, cached reads and reset PASS")

    hook.rt_mod_begin.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    hook.rt_mod_begin.restype = None
    status = folder / "mods/stable60-v2.status.txt"
    build_id = b"AE16F71E002AF8CB059A9A74C4D90F34BA984892"
    capability = b"stable60-v2:" + build_id + b":01019608,01019628"
    marker.write_bytes(build_id + b"\n")
    hook.rt_mod_begin(None, None)
    assert "sem suporte ao mod" in status.read_text()
    assert hook.rt_mod_nop(0x7001019608) == 0  # config cannot activate an unprepared module
    hook.rt_mod_begin(capability, build_id.lower())
    assert "Seleção carregada: ativada" in status.read_text()
    assert "Aguardando execução" in status.read_text()
    assert "NOP executado" not in status.read_text()
    assert hook.rt_mod_nop(0x7001019608) == 1
    assert "NOP executado em main+01019608" in status.read_text()
    assert "NOP executado em main+01019628" not in status.read_text()
    stamp = status.stat().st_mtime_ns
    assert hook.rt_mod_nop(0x7001019608) == 1
    assert status.stat().st_mtime_ns == stamp  # no file writes on repeated calls
    assert hook.rt_mod_nop(0x7001019628) == 1
    assert "NOP executado em main+01019628" in status.read_text()
    marker.write_text("disabled\n")
    assert hook.rt_mod_nop(0x7001019608) == 1  # selection stays cached during gameplay
    hook.test_reset()
    assert "Seleção carregada: desativada" in status.read_text()
    assert "NOP executado" not in status.read_text()
    assert hook.rt_mod_nop(0x7001019608) == 0
    hook.rt_mod_begin(None, build_id.lower())
    assert "Mod fixo: ativado" in status.read_text()
    hook.rt_mod_begin(b"wrong-capability", build_id.lower())
    assert "sem suporte ao mod" in status.read_text()  # incompatible variant isn't a fixed patch
    print("Last-session status: actual module, selection, both applied NOPs, cache and reset PASS")

    # Exercise the actual Android gamelib loader on the host, independently of
    # the mocked JNI probe below. Only a tiny synthetic module is loaded.
    loader = folder / "game-loader.so"
    subprocess.run([*shlex.split(os.environ.get("CC", "clang")), "-std=gnu11", "-shared", "-fPIC", "-O1",
                    "-D__ANDROID__", str(ROOT / "runtime/gamelib.c"), str(ROOT / "runtime/mods.c"),
                    "-ldl", "-o", str(loader)], check=True)
    for kind in ("original", "menu", "fixed"):
        private = folder / ("loader-" + kind)
        (private / "files/mods").mkdir(parents=True)
        (private / "code_cache").mkdir()
        (private / "files/mods/stable60-v2.enabled").write_bytes(build_id + b"\n")
        module_source = private / "synthetic.c"
        code = '#include "' + str(ROOT / "runtime/gamelib.h") + '"\n'
        code += ('static const uint64_t address=0x7000000000ull, count=1;\n'
                 'static void guest(Cpu *c) { (void)c; }\n'
                 'static const GuestFn function=guest;\n'
                 'static const GameLibTables table={GAMELIB_ABI,GAMELIB_ID,&address,&address,\n'
                 '    &function,&function,&count,&count};\n'
                 'GAMELIB_EXPORT const GameLibTables *lasgame_tables(void) { return &table; }\n')
        if kind in ("menu", "fixed"):
            code += 'const char *lasgame_mod_stable60_v2(void) { return "' + build_id.lower().decode() + '"; }\n'
        if kind == "menu":
            code += 'const char *lasgame_mod_menu_v1(void) { return "' + capability.decode() + '"; }\n'
        module_source.write_text(code)
        module = private / "code_cache/liblasgame.so"
        subprocess.run([*shlex.split(os.environ.get("CC", "clang")), "-std=gnu11", "-shared", "-fPIC", "-O1",
                        str(module_source), "-o", str(module)], check=True)
        module.chmod(0o400)
        probe = '''
import ctypes, os, pathlib, sys
os.environ['LARECOMP_DATA_ROOT'] = sys.argv[2]
loader = ctypes.CDLL(sys.argv[1])
loader.gamelib_load.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
loader.gamelib_load.restype = ctypes.c_bool
error = ctypes.create_string_buffer(512)
assert loader.gamelib_load(b'extracted', error, len(error)), error.value
status = (pathlib.Path(sys.argv[2]) / 'mods/stable60-v2.status.txt').read_text()
expected = {'original':'sem suporte ao mod', 'menu':'Seleção carregada: ativada', 'fixed':'Mod fixo: ativado'}
assert expected[sys.argv[3]] in status, status
'''
        subprocess.run([sys.executable, "-c", probe,
                        str(loader), str(private / "files"), kind], check=True)
    print("Production Android game-loader path: original/menu/fixed module status PASS (host ELF)")

    jdk = Path(os.environ.get("JAVA_HOME", Path(java).resolve().parents[1]))
    jni_test = folder / "mod-library-test"
    subprocess.run([*shlex.split(os.environ.get("CC", "clang")), "-std=gnu11", "-O1",
                    "-I" + str(jdk / "include"), "-I" + str(jdk / "include/linux"),
                    str(ROOT / "tests/mod_library_test.c"), "-o", str(jni_test)], check=True)
    subprocess.run([str(jni_test), str(folder / "private-game.so")], check=True)
